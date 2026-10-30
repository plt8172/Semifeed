#!/usr/bin/env python3
"""릴스 한 편(에피소드 폴더)을 나레이션·장면·효과음까지 합쳐 1080×1920 MP4로 만든다.

    python3 reels/reel.py check   reels/episodes/<slug>   episode.json과 장면 파일 검사
    python3 reels/reel.py tts     reels/episodes/<slug>   장면별 나레이션 음성 생성 (문장이 같으면 재사용)
    python3 reels/reel.py preview reels/episodes/<slug>   장면마다 정지 화면 3장 → build/preview.png
    python3 reels/reel.py build   reels/episodes/<slug>   tts → 렌더 → 믹스 → out/<slug>.mp4
    python3 reels/reel.py codec   in.wav out_dir/         같은 음성을 PCM·GSM·Codec2로 통과시킨 A/B/C.wav
    python3 reels/reel.py setup                           오프라인 TTS 모델 받기 (OPENAI_API_KEY가 없을 때)

에피소드 폴더 구조와 episode.json 형식은 reels/AGENTS.md에 있다.
장면은 HTML 파일이고 reels/kit/kit.js의 Reel.scene((t, R) => ...)로 시간 t의 화면을 그린다.
이 스크립트는 판단을 하지 않는다. 대본과 장면은 에이전트가 쓰고, 여기서는 정해진 대로 합치기만 한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

REELS = Path(__file__).resolve().parent
MODELS = REELS / ".models"
SHERPA_MODEL = "vits-mimic3-ko_KO-kss_low"
SHERPA_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{SHERPA_MODEL}.tar.bz2"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium"
SR = 24000
W, H = 1080, 1920
CLIP_SR = 4000


# ---------- 에피소드 읽기 ----------

def load_episode(ep: Path) -> dict:
    data = json.loads((ep / "episode.json").read_text(encoding="utf-8"))
    data.setdefault("fps", 30)
    data.setdefault("voice", {})
    data.setdefault("bgm", {"type": "pulse", "bpm": 100, "gain": 0.12})
    for s in data["scenes"]:
        s.setdefault("pad", [0.3, 0.4])
        s.setdefault("clips", [])
        s.setdefault("waves", [])
        s.setdefault("sfx", [])
        s.setdefault("transition", True)
    return data


def check(ep: Path) -> list[str]:
    """문제 목록을 돌려준다. 빈 목록이면 통과."""
    errs = []
    try:
        data = load_episode(ep)
    except (OSError, ValueError, KeyError) as e:
        return [f"episode.json을 읽을 수 없음: {e}"]
    if not data.get("title"):
        errs.append("title 없음")
    ids = set()
    for i, s in enumerate(data["scenes"]):
        sid = s.get("id") or f"#{i}"
        if sid in ids:
            errs.append(f"{sid}: id 중복")
        ids.add(sid)
        if not s.get("html") or not (ep / s["html"]).is_file():
            errs.append(f"{sid}: html 파일 없음 ({s.get('html')})")
        if not s.get("narration") and not s.get("duration"):
            errs.append(f"{sid}: narration도 duration도 없음")
        for c in s["clips"] + [{"file": w} for w in s["waves"]]:
            if not (ep / c["file"]).is_file():
                errs.append(f"{sid}: 오디오 파일 없음 ({c['file']})")
        for chunk in caption_chunks(s.get("caption") or s.get("narration", "")):
            if len(chunk) > 22:
                errs.append(f"{sid}: 자막 한 덩어리가 22자를 넘음, 쉼표로 끊기: {chunk}")
    return errs


# ---------- TTS ----------

def tts_backend(voice: dict) -> str:
    b = voice.get("backend", "auto")
    if b != "auto":
        return b
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if (MODELS / SHERPA_MODEL / "tokens.txt").is_file():
        return "sherpa"
    return "silence"


def tts_openai(text: str, voice: dict, out: Path) -> None:
    body = {
        "model": voice.get("model", "gpt-4o-mini-tts"),
        "voice": voice.get("openai_voice", "coral"),
        "input": text,
        "response_format": "wav",
        "instructions": voice.get("instructions", "한국어로, 친구에게 신기한 사실을 알려 주듯 밝고 또렷하게. 너무 빠르지 않게."),
    }
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())


_sherpa = None


def tts_sherpa(text: str, voice: dict, out: Path) -> None:
    global _sherpa
    import sherpa_onnx
    if _sherpa is None:
        d = MODELS / SHERPA_MODEL
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(d / "ko_KO-kss_low.onnx"), lexicon="",
                                                       tokens=str(d / "tokens.txt"), data_dir=str(d / "espeak-ng-data")),
            num_threads=4))
        _sherpa = sherpa_onnx.OfflineTts(cfg)
    a = _sherpa.generate(text, sid=0, speed=voice.get("speed", 1.0))
    sf.write(out, np.asarray(a.samples), a.sample_rate)


def tts_silence(text: str, voice: dict, out: Path) -> None:
    # 레이아웃 확인용: 한 글자 0.13초로 어림한 무음
    sf.write(out, np.zeros(int(SR * max(1.0, 0.13 * len(text)))), SR)


def read_mono(path: Path, sr: int = SR) -> np.ndarray:
    x, r = sf.read(path, always_2d=True)
    x = x.mean(1)
    if r != sr:
        from scipy.signal import resample_poly
        g = math.gcd(r, sr)
        x = resample_poly(x, sr // g, r // g)
    return x.astype(np.float64)


def run_tts(ep: Path, data: dict) -> dict:
    """장면별 나레이션 wav를 만들고 {scene_id: 길이(초)}를 돌려준다."""
    vo = ep / "build" / "vo"
    vo.mkdir(parents=True, exist_ok=True)
    backend = tts_backend(data["voice"])
    fn = {"openai": tts_openai, "sherpa": tts_sherpa, "silence": tts_silence}[backend]
    durs = {}
    for s in data["scenes"]:
        text = s.get("narration", "").strip()
        if not text:
            durs[s["id"]] = 0.0
            continue
        key = hashlib.sha1(json.dumps([backend, data["voice"], text], ensure_ascii=False).encode()).hexdigest()[:12]
        out = vo / f"{s['id']}.{key}.wav"
        if not out.is_file():
            print(f"tts[{backend}] {s['id']}: {text}", flush=True)
            fn(text, data["voice"], out)
        durs[s["id"]] = len(read_mono(out)) / SR
        shutil.copyfile(out, vo / f"{s['id']}.wav")
    (ep / "build" / "tts.json").write_text(json.dumps({"backend": backend, "durations": durs}, indent=1))
    if backend == "silence":
        print("경고: TTS 백엔드가 없어 무음으로 만들었습니다. OPENAI_API_KEY를 설정하거나 `reel.py setup`을 실행하세요.")
    return durs


# ---------- 시간표 ----------

def caption_chunks(text: str) -> list[str]:
    parts, cur = [], ""
    for i, ch in enumerate(text):
        cur += ch
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch in ",.?!" and not (ch == "," and cur[-2:-1].isdigit() and nxt.isdigit()) and len(cur.strip()) > 4:
            parts.append(cur.strip().rstrip(",."))
            cur = ""
    if cur.strip():
        parts.append(cur.strip().rstrip(",."))
    return [p for p in parts if p]


def resolve_at(at, vo_start: float, vo_dur: float) -> float:
    """시각 표기: 숫자(장면 시작부터 초), "vo:0.5"(나레이션의 50% 지점), "vo+0.3"(나레이션 끝 + 0.3초)."""
    if isinstance(at, (int, float)):
        return float(at)
    m = re.fullmatch(r"vo:([\d.]+)", str(at))
    if m:
        return vo_start + float(m.group(1)) * vo_dur
    m = re.fullmatch(r"vo\+([\d.]+)", str(at))
    if m:
        return vo_start + vo_dur + float(m.group(1))
    raise ValueError(f"알 수 없는 시각 표기: {at}")


def plan(ep: Path, data: dict, durs: dict) -> dict:
    fps = data["fps"]
    t = 0.0
    scenes = []
    for s in data["scenes"]:
        vo_start, vo_dur = s["pad"][0], durs.get(s["id"], 0.0)
        end = vo_start + vo_dur
        clips = []
        for c in s["clips"]:
            at = resolve_at(c.get("at", "vo+0.3"), vo_start, vo_dur)
            n = len(read_mono(ep / c["file"]))
            clips.append({"file": c["file"], "at": at, "duration": n / SR, "gain": c.get("gain", 0.8)})
            end = max(end, at + n / SR)
        dur = s.get("duration") or end + s["pad"][1]
        dur = round(dur * fps) / fps
        if s.get("captions"):
            caps = [{"t0": a, "t1": b, "text": x} for a, b, x in s["captions"]]
        else:
            chunks = caption_chunks(s.get("caption") or s.get("narration", ""))
            tot = sum(map(len, chunks)) or 1
            caps, acc = [], 0
            for i, c in enumerate(chunks):
                a = vo_start + vo_dur * acc / tot
                acc += len(c)
                b = vo_start + vo_dur * acc / tot + (0.25 if i < len(chunks) - 1 else 0.5)
                caps.append({"t0": a - 0.05, "t1": min(b, dur), "text": c})
        sfx = [{"type": x["type"], "at": resolve_at(x["at"], vo_start, vo_dur), "gain": x.get("gain", 0.3)} for x in s["sfx"]]
        scenes.append({"id": s["id"], "html": s["html"], "start": t, "duration": dur, "vo_start": vo_start,
                       "vo_duration": vo_dur, "clips": clips, "waves": s["waves"], "captions": caps, "sfx": sfx,
                       "transition": s["transition"], "frames": int(round(dur * fps))})
        t += dur
    p = {"title": data["title"], "fps": fps, "total": t, "scenes": scenes, "bgm": data["bgm"]}
    (ep / "build" / "plan.json").write_text(json.dumps(p, ensure_ascii=False, indent=1))
    return p


# ---------- 오디오 ----------

def synth_sfx(kind: str, rng: np.random.RandomState) -> np.ndarray:
    from scipy.signal import lfilter
    def tt(d):
        return np.arange(int(d * SR)) / SR
    if kind == "pop":
        x = tt(0.09)
        return np.sin(2 * np.pi * 880 * x * (1 + 0.5 * np.exp(-x * 40))) * np.exp(-x * 35)
    if kind == "hit":
        x = tt(0.5)
        return np.sin(2 * np.pi * (45 + 90 * np.exp(-x * 25)) * x) * np.exp(-x * 7) + 0.25 * rng.randn(len(x)) * np.exp(-x * 30)
    if kind == "tick":
        x = tt(0.03)
        return np.sin(2 * np.pi * 2400 * x) * np.exp(-x * 200)
    if kind == "whoosh":
        m = int(0.35 * SR)
        y = lfilter([1], [1, -0.97], rng.randn(m))
        return y / np.abs(y).max() * np.sin(np.pi * np.arange(m) / m) ** 2
    if kind == "ding":
        x = tt(0.6)
        return (np.sin(2 * np.pi * 1320 * x) + 0.5 * np.sin(2 * np.pi * 1980 * x)) * np.exp(-x * 6)
    raise ValueError(f"알 수 없는 효과음: {kind} (pop, hit, tick, whoosh, ding)")


def scene_audio(ep: Path, s: dict) -> tuple[np.ndarray, np.ndarray]:
    """장면 하나의 (전경 오디오, 배경음을 줄일 구간 마스크)."""
    n = int(round(s["duration"] * SR))
    out, duck = np.zeros(n), np.ones(n)
    def add(sig, at, g=1.0):
        i = int(at * SR)
        if i >= n:
            return
        sig = sig[: n - i]
        out[i:i + len(sig)] += g * sig
    vo = ep / "build" / "vo" / f"{s['id']}.wav"
    if s["vo_duration"] and vo.is_file():
        add(read_mono(vo), s["vo_start"], 0.95)
    for c in s["clips"]:
        x = read_mono(ep / c["file"])
        add(x / (np.abs(x).max() + 1e-9), c["at"], c["gain"])
        a, b = int((c["at"] - 0.1) * SR), int((c["at"] + c["duration"] + 0.1) * SR)
        duck[max(0, a):max(0, b)] = 0.0
    rng = np.random.RandomState(abs(hash(s["id"])) % 2**31)
    if s["transition"] and s["start"] > 0:
        add(synth_sfx("whoosh", rng), 0.0, 0.2)
    for x in s["sfx"]:
        add(synth_sfx(x["type"], rng), x["at"], x["gain"])
    return out, duck


def mix(ep: Path, p: dict) -> Path:
    from scipy.ndimage import uniform_filter1d
    parts, ducks = zip(*(scene_audio(ep, s) for s in p["scenes"]))
    fg, duck = np.concatenate(parts), np.concatenate(ducks)
    bed = np.zeros_like(fg)
    b = p["bgm"]
    if b.get("type") == "pulse":
        step = 60 / b.get("bpm", 100)
        x = np.arange(int(0.25 * SR)) / SR
        kick = np.sin(2 * np.pi * (50 + 60 * np.exp(-x * 30)) * x) * np.exp(-x * 14)
        k = 0
        while k * step < p["total"] - 0.8:
            i = int(k * step * SR)
            seg = kick[: max(0, len(bed) - i)]
            bed[i:i + len(seg)] += seg
            k += 1
    elif b.get("type") == "file":
        x = read_mono(ep / b["file"])
        bed[: len(x)] = x[: len(bed)]
    duck = uniform_filter1d(duck, int(0.08 * SR))
    outro = np.clip((p["total"] - np.arange(len(fg)) / SR) / 1.0, 0, 1)
    y = fg + b.get("gain", 0.12) * bed * duck * outro
    y = y / max(1.0, np.abs(y).max() / 0.97)
    path = ep / "build" / "audio.wav"
    sf.write(path, y, SR)
    return path


def envelope(ep: Path, p: dict, s: dict) -> list[float]:
    """장면 전경 오디오의 프레임별 세기(0~1)."""
    a, _ = scene_audio(ep, s)
    hop = SR // p["fps"]
    n = s["frames"]
    a = np.pad(a, (0, max(0, n * hop - len(a))))[: n * hop].reshape(n, hop)
    e = np.sqrt((a ** 2).mean(1))
    return [round(float(v), 3) for v in np.clip(e / 0.25, 0, 1)]


def clip_samples(ep: Path, files: list[str]) -> dict:
    out = {}
    for f in files:
        x = read_mono(ep / f, CLIP_SR)
        out[f] = [round(float(v), 3) for v in x / (np.abs(x).max() + 1e-9)]
    return out


# ---------- 렌더 ----------

def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        return pw.chromium.launch(executable_path=FALLBACK_CHROMIUM)


def open_scene(pw_browser, ep: Path, p: dict, s: dict):
    page = pw_browser.new_page(viewport={"width": W, "height": H})
    reel = {"scene": {k: s[k] for k in ("id", "duration", "vo_start", "vo_duration", "captions")},
            "env": envelope(ep, p, s), "clips": clip_samples(ep, [c["file"] for c in s["clips"]] + s["waves"]),
            "fps": p["fps"], "global_start": s["start"], "total": p["total"]}
    page.add_init_script("window.REEL = " + json.dumps(reel, ensure_ascii=False) + ";")
    page.goto((ep / s["html"]).resolve().as_uri())
    page.evaluate("document.fonts.ready")
    if not page.evaluate("typeof window.seek === 'function'"):
        raise SystemExit(f"{s['id']}: 장면이 Reel.scene(...)을 호출하지 않았습니다 ({s['html']})")
    return page


def render_scene(args) -> str:
    ep, p, idx = args
    from playwright.sync_api import sync_playwright
    s = p["scenes"][idx]
    out = ep / "build" / "scenes" / f"{idx:02d}_{s['id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(p["fps"]),
                           "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                           "-r", str(p["fps"]), str(out)], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        b = launch(pw)
        page = open_scene(b, ep, p, s)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for i in range(s["frames"]):
            page.evaluate(f"window.seek({i / p['fps']:.4f})")
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
        b.close()
    ff.stdin.close()
    ff.wait()
    if errors:
        raise SystemExit(f"{s['id']}: 장면 스크립트 오류: {errors[0]}")
    return str(out)


def render(ep: Path, p: dict) -> Path:
    jobs = [(ep, p, i) for i in range(len(p["scenes"]))]
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        files = list(pool.map(render_scene, jobs))
    lst = ep / "build" / "scenes.txt"
    lst.write_text("".join(f"file '{Path(f).resolve()}'\n" for f in files))
    video = ep / "build" / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(video)], check=True)
    return video


def preview(ep: Path, p: dict, fracs=(0.15, 0.5, 0.85)) -> Path:
    from playwright.sync_api import sync_playwright
    d = ep / "build" / "preview"
    d.mkdir(parents=True, exist_ok=True)
    shots = []
    with sync_playwright() as pw:
        b = launch(pw)
        for s in p["scenes"]:
            page = open_scene(b, ep, p, s)
            for f in fracs:
                path = d / f"{s['id']}_{int(f * 100):02d}.jpg"
                page.evaluate(f"window.seek({f * s['duration']:.3f})")
                page.screenshot(path=str(path), type="jpeg", quality=80)
                shots.append(path)
            page.close()
        b.close()
    cols = len(fracs)
    rows = [shots[i:i + cols] for i in range(0, len(shots), cols)]
    out = ep / "build" / "preview.png"
    inputs = sum((["-i", str(x)] for x in shots), [])
    flt = "".join(f"[{i}]scale=270:-1[s{i}];" for i in range(len(shots)))
    flt += "".join("".join(f"[s{r * cols + c}]" for c in range(len(row))) + f"hstack={len(row)}[r{r}];"
                   if len(row) > 1 else f"[s{r * cols}]null[r{r}];" for r, row in enumerate(rows))
    flt += "".join(f"[r{r}]" for r in range(len(rows))) + (f"vstack={len(rows)}" if len(rows) > 1 else "null")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", flt, str(out)], check=True)
    return out


def build(ep: Path) -> Path:
    errs = check(ep)
    if errs:
        raise SystemExit("episode 검사 실패:\n- " + "\n- ".join(errs))
    data = load_episode(ep)
    p = plan(ep, data, run_tts(ep, data))
    video = render(ep, p)
    audio = mix(ep, p)
    out = ep / "out" / f"{ep.name}.mp4"
    out.parent.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out)],
                   check=True)
    print(f"완성: {out} ({p['total']:.1f}초, 장면 {len(p['scenes'])}개)")
    return out


# ---------- 보조 도구 ----------

def codec_demo(src: Path, out: Path) -> None:
    """같은 음성을 전화 PCM(64k)·GSM(13k)·Codec2(700bps)로 인코딩했다 복원한 A/B/C.wav."""
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_8k.wav"
    run = lambda *a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
    run("-i", str(src), "-ar", "8000", "-ac", "1", str(tmp))
    for name, enc, fmt in (("A", "pcm_mulaw", "mulaw"), ("B", "libgsm", "gsm"), ("C", "libcodec2", "codec2")):
        raw = out / f"_{name}.{fmt}"
        extra = ["-mode", "700C"] if enc == "libcodec2" else []
        run("-i", str(tmp), "-c:a", enc, *extra, "-f", fmt, str(raw))
        dec = ["-f", fmt, "-ar", "8000"] if fmt != "codec2" else []
        run(*dec, "-i", str(raw), str(out / f"{name}.wav"))
        print(name, enc, f"{raw.stat().st_size * 8 / sf.info(tmp).duration:.0f} bit/s")
        raw.unlink()
    tmp.unlink()


def setup() -> None:
    MODELS.mkdir(exist_ok=True)
    if (MODELS / SHERPA_MODEL / "tokens.txt").is_file():
        print("이미 있음:", MODELS / SHERPA_MODEL)
        return
    arc = MODELS / "model.tar.bz2"
    print("받는 중:", SHERPA_URL)
    urllib.request.urlretrieve(SHERPA_URL, arc)
    with tarfile.open(arc) as t:
        t.extractall(MODELS, filter="data")
    arc.unlink()
    print("완료:", MODELS / SHERPA_MODEL)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "tts", "preview", "build", "codec", "setup"])
    ap.add_argument("paths", nargs="*")
    a = ap.parse_args()
    if a.cmd == "setup":
        return setup()
    if a.cmd == "codec":
        return codec_demo(Path(a.paths[0]), Path(a.paths[1]))
    ep = Path(a.paths[0])
    if a.cmd == "check":
        errs = check(ep)
        print("통과" if not errs else "문제:\n- " + "\n- ".join(errs))
        sys.exit(1 if errs else 0)
    data = load_episode(ep)
    durs = run_tts(ep, data)
    if a.cmd == "tts":
        print(json.dumps(durs, ensure_ascii=False))
        return
    if a.cmd == "preview":
        print(preview(ep, plan(ep, data, durs)))
        return
    build(ep)


if __name__ == "__main__":
    main()
