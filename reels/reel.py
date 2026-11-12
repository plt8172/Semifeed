#!/usr/bin/env python3
"""릴스 한 편(에피소드 폴더)을 나레이션·무대·효과음까지 합쳐 1080×1920 MP4로 만든다.

    python3 reels/reel.py check   reels/episodes/<slug>            episode.json과 파일 검사
    python3 reels/reel.py plan    reels/episodes/<slug>            TTS를 만들고 시간표(build/plan.json)를 출력
    python3 reels/reel.py preview reels/episodes/<slug>            줄마다 정지 화면 → build/preview.png
    python3 reels/reel.py frames  reels/episodes/<slug> 3.2 h2 ... 지정한 시각(초 또는 줄 id)의 원본 크기 화면 → build/frames/
    python3 reels/reel.py build   reels/episodes/<slug>            tts → 렌더 → 믹스 → out/<slug>.mp4
    python3 reels/reel.py codec   in.wav out_dir/                  같은 음성을 PCM·GSM·Codec2로 통과시킨 A/B/C.wav
    python3 reels/reel.py say     "문장" out.wav [목소리 번호]        TTS로 문장 하나를 wav로 (데모 음성 재료)
    python3 reels/reel.py listen  reels/episodes/<slug>            완성 영상의 소리를 줄마다 받아 적어 자막과 나란히 출력
    python3 reels/reel.py listen  any.wav|mp4                      오디오 파일을 받아 적는다 (데모 음성이 들리는지 확인)
    python3 reels/reel.py setup                                    내장 TTS 모델 받기 (약 130MB. 키 없이 쓰는 기본 목소리)
    python3 reels/reel.py setup   asr                              받아쓰기(음성 인식) 모델 받기 (listen에 필요, 약 640MB)

에피소드는 나레이션 줄 목록(episode.json의 lines)과 무대 하나(stage.html)로 이루어진다.
이 스크립트가 줄마다 음성을 만들고 단어 단위 시간표를 계산하면, 무대는 그 시간표에 맞춰 시간 t의 화면을 그린다.
형식은 reels/AGENTS.md에 있다. 이 스크립트는 판단을 하지 않는다. 대본과 무대는 에이전트가 쓴다.
"""

from __future__ import annotations

import argparse
import difflib
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
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

REELS = Path(__file__).resolve().parent
MODELS = REELS / ".models"
TTS_MODEL = "sherpa-onnx-supertonic-3-tts-int8-2026-05-11"      # Supertonic 3: 목소리 10개(sid 0~9), 44.1 kHz
TTS_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{TTS_MODEL}.tar.bz2"
TTS_SID, TTS_SPEED = 2, 1.12
TAKES, TAKE_OK = 4, 0.95           # 내장 TTS: 받아쓰기가 대본과 이만큼 맞을 때까지 다시 읽히는 횟수
ASR_MODEL = "sherpa-onnx-whisper-small"
ASR_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{ASR_MODEL}.tar.bz2"
FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium"
SR = 24000
W, H = 1080, 1920
CLIP_SR = 4000
LEAD, TAIL = 0.35, 0.9          # 영상 맨 앞·맨 뒤 여백(초)
CAPTION_MAX = 14                # 자막 한 덩어리의 최대 글자 수(공백 제외)
BREAKS = ",.?!"


# ---------- 에피소드 읽기 ----------

def load_episode(ep: Path) -> dict:
    data = json.loads((ep / "episode.json").read_text(encoding="utf-8"))
    data.setdefault("fps", 30)
    data.setdefault("voice", {})
    data.setdefault("bgm", {"type": "pad", "gain": 0.03})
    data.setdefault("stage", "stage.html")
    data.setdefault("waves", [])
    for ln in data["lines"]:
        ln.setdefault("say", "")
        ln.setdefault("caption", ln["say"])
        ln.setdefault("after", 0.3)
        ln.setdefault("clips", [])
        ln.setdefault("sfx", [])
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
    if not (ep / data["stage"]).is_file():
        errs.append(f"무대 파일 없음 ({data['stage']})")
    ids = set()
    for i, ln in enumerate(data["lines"]):
        lid = ln.get("id") or f"#{i}"
        if not ln.get("id"):
            errs.append(f"{lid}: id 없음")
        if lid in ids:
            errs.append(f"{lid}: id 중복")
        ids.add(lid)
        if not ln["say"] and not ln["clips"] and not ln.get("dur"):
            errs.append(f"{lid}: say도 clips도 dur도 없음")
        for c in ln["clips"]:
            if not (ep / c["file"]).is_file():
                errs.append(f"{lid}: 오디오 파일 없음 ({c['file']})")
        for w in ln["caption"].split():
            if len(w) > CAPTION_MAX:
                errs.append(f"{lid}: 자막 단어가 {CAPTION_MAX}자를 넘음: {w}")
    for f in data["waves"]:
        if not (ep / f).is_file():
            errs.append(f"waves: 오디오 파일 없음 ({f})")
    return errs


# ---------- TTS ----------

def tts_backend(voice: dict) -> str:
    b = voice.get("backend", "auto")
    if b != "auto":
        return b
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if (MODELS / TTS_MODEL / "tts.json").is_file():
        return "local"
    return "silence"


def tts_openai(text: str, voice: dict, out: Path) -> None:
    body = {
        "model": voice.get("model", "gpt-4o-mini-tts"),
        "voice": voice.get("openai_voice", "coral"),
        "input": text,
        "response_format": "wav",
        "instructions": voice.get("instructions", "한국어로, 담백하고 또렷하게. 과장 없이 차분한 속도로."),
    }
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        out.write_bytes(r.read())


_local = None


def tts_local(text: str, voice: dict, out: Path) -> None:
    """내장 모델(Supertonic 3)로 읽는다. voice: sid(목소리 0~9), speed(말 빠르기), steps.
    모델의 speed를 올리면 어미가 뭉개지므로, 1.0으로 만든 뒤 음높이를 지키며(atempo) 빠르게 한다."""
    global _local
    import sherpa_onnx
    if _local is None:
        d = MODELS / TTS_MODEL
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            supertonic=sherpa_onnx.OfflineTtsSupertonicModelConfig(
                duration_predictor=str(d / "duration_predictor.int8.onnx"), text_encoder=str(d / "text_encoder.int8.onnx"),
                vector_estimator=str(d / "vector_estimator.int8.onnx"), vocoder=str(d / "vocoder.int8.onnx"),
                tts_json=str(d / "tts.json"), unicode_indexer=str(d / "unicode_indexer.bin"), voice_style=str(d / "voice.bin")),
            num_threads=4))
        _local = sherpa_onnx.OfflineTts(cfg)
    gc = sherpa_onnx.GenerationConfig()
    gc.sid, gc.num_steps, gc.speed = int(voice.get("sid", TTS_SID)), int(voice.get("steps", 8)), 1.0
    gc.extra["lang"] = voice.get("lang", "ko")
    a = _local.generate(text, gc)
    speed = float(voice.get("speed", TTS_SPEED))
    if abs(speed - 1) < 0.01:
        sf.write(out, np.asarray(a.samples), a.sample_rate)
        return
    raw = out.with_suffix(".raw.wav")
    sf.write(raw, np.asarray(a.samples), a.sample_rate)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", f"atempo={speed}", str(out)], check=True)
    raw.unlink()


def tts_silence(text: str, voice: dict, out: Path) -> None:
    # 레이아웃 확인용: 한 글자 0.13초로 어림한 무음
    sf.write(out, np.zeros(int(SR * max(0.6, 0.13 * len(text)))), SR)


TTS = {"openai": tts_openai, "local": tts_local, "silence": tts_silence}


def read_mono(path: Path, sr: int = SR) -> np.ndarray:
    x, r = sf.read(path, always_2d=True)
    x = x.mean(1)
    if r != sr:
        from scipy.signal import resample_poly
        g = math.gcd(r, sr)
        x = resample_poly(x, sr // g, r // g)
    return x.astype(np.float64)


def voiced_runs(x: np.ndarray, min_gap: float = 0.14) -> list[tuple[float, float]]:
    """소리가 나는 구간 목록(초). min_gap보다 짧은 쉼은 한 구간으로 본다. 소리가 없으면 빈 목록."""
    hop = SR // 100
    n = len(x) // hop
    if n == 0:
        return []
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1))
    if e.max() < 1e-4:
        return []
    on = e > 0.06 * e.max()
    runs, start, last = [], None, None
    for i, v in enumerate(on):
        if not v:
            continue
        if start is None:
            start = i
        elif (i - last) * hop / SR >= min_gap:
            runs.append((start, last + 1))
            start = i
        last = i
    runs.append((start, last + 1))
    return [(a * hop / SR, b * hop / SR) for a, b in runs]


def run_tts(ep: Path, data: dict) -> dict:
    """줄마다 나레이션 wav(앞뒤 무음 제거)를 만들고 {id: {"dur": 길이, "runs": 소리 구간}}을 돌려준다."""
    vo = ep / "build" / "vo"
    vo.mkdir(parents=True, exist_ok=True)
    backend = tts_backend(data["voice"])
    info = {}
    for ln in data["lines"]:
        text = ln["say"].strip()
        if not text:
            info[ln["id"]] = {"dur": 0.0, "runs": []}
            continue
        key = hashlib.sha1(json.dumps([backend, data["voice"], text], ensure_ascii=False).encode()).hexdigest()[:12]
        raw = vo / f"{ln['id']}.{key}.wav"
        if not raw.is_file():
            TTS[backend](text, data["voice"], raw)
            note = ""
            if backend == "local" and have_asr():
                # 내장 모델은 읽을 때마다 조금씩 다르다. 받아 적어서 대본과 가장 가까운 것을 쓴다
                def score(f):
                    return heard_ratio(hear(read_mono(f, 16000)), text, ln["caption"])
                best, n = score(raw), 1
                while best < TAKE_OK and n < TAKES:
                    alt = raw.with_suffix(".alt.wav")
                    TTS[backend](text, data["voice"], alt)
                    got, n = score(alt), n + 1
                    if got > best:
                        alt.replace(raw)
                        best = got
                    else:
                        alt.unlink()
                note = f"  (받아쓰기 일치 {best:.2f}, {n}번 읽음)"
            print(f"tts[{backend}] {ln['id']}: {text}{note}", flush=True)
        x = read_mono(raw)
        runs = voiced_runs(x)
        if runs:
            a, b = max(0.0, runs[0][0] - 0.03), min(len(x) / SR, runs[-1][1] + 0.06)
            x = x[int(a * SR): int(b * SR)]
            runs = [(max(0.0, s - a), e - a) for s, e in runs]
            x = x / max(np.abs(x).max(), 1e-9) * 0.9
        sf.write(vo / f"{ln['id']}.wav", x, SR)
        info[ln["id"]] = {"dur": len(x) / SR, "runs": runs}
    (ep / "build" / "tts.json").write_text(json.dumps({"backend": backend, "lines": info}, indent=1))
    if backend == "silence":
        print("경고: TTS가 없어 무음으로 만들었습니다. `python3 reels/reel.py setup`으로 내장 모델을 받으세요.")
    return info


# ---------- 시간표 ----------

def spoken_len(word: str) -> int:
    """단어를 소리 내는 데 걸리는 길이의 어림값(글자 수). 숫자는 한글로 읽으면 길어진다."""
    n = 0
    for ch in word:
        if ch.isdigit():
            n += 2
        elif ch.isalnum():
            n += 1
    return max(n, 1)


def split_phrases(text: str) -> list[list[str]]:
    """문장부호(, . ? !)에서 끊은 구 목록. 구는 단어 목록이다. 숫자 사이 쉼표(8,000)는 끊지 않는다."""
    phrases, cur = [], []
    for w in text.split():
        cur.append(w)
        if w.rstrip("'\"”’)")[-1:] in BREAKS:
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    return phrases


def word_times(caption: str, say: str, dur: float, runs: list) -> list[dict]:
    """자막 단어마다 말하기 시작·끝 시각(줄 시작 기준)을 어림한다.

    음성의 쉼 개수가 문장부호로 나뉜 구 개수와 맞으면 구마다 실제 소리 구간에 맞추고,
    아니면 줄 전체에 글자 수 비율로 나눈다.
    """
    phrases = split_phrases(caption)
    if not phrases or dur <= 0:
        return []
    cap_words = [w for ph in phrases for w in ph]
    say_words = say.split()
    weights = [spoken_len(w) for w in (say_words if len(say_words) == len(cap_words) else cap_words)]
    if len(runs) == len(phrases):
        spans, groups = runs, phrases
    else:
        spans, groups = [(0.0, dur)], [cap_words]
    out, k = [], 0
    for (a, b), words in zip(spans, groups):
        tot = sum(weights[k:k + len(words)])
        acc = 0
        for w in words:
            t0 = a + (b - a) * acc / tot
            acc += weights[k]
            out.append({"w": w, "t0": t0, "t1": a + (b - a) * acc / tot})
            k += 1
    return out


def caption_groups(words: list[dict]) -> list[list[dict]]:
    """화면에 한 번에 띄울 자막 덩어리. 문장부호에서 끊고, 길면 단어 경계에서 고르게 나눈다."""
    groups, phrase = [], []

    def flush():
        if not phrase:
            return
        n = sum(len(w["w"]) for w in phrase)
        parts = max(1, math.ceil(n / CAPTION_MAX))
        g, acc, made = [], 0, 0
        for w in phrase:
            if g and made < parts - 1 and acc + len(w["w"]) / 2 > n / parts * (made + 1):
                groups.append(g)
                g, made = [], made + 1
            g.append(w)
            acc += len(w["w"])
        groups.append(g)
        phrase.clear()

    for w in words:
        phrase.append(w)
        if w["w"].rstrip("'\"”’)")[-1:] in BREAKS:
            flush()
    flush()
    return groups


def clean_word(w: str) -> str:
    return w.rstrip(",.")


def plan(ep: Path, data: dict, tts: dict) -> dict:
    fps = data["fps"]
    t = LEAD
    lines, caps = [], []
    for ln in data["lines"]:
        v = tts[ln["id"]]
        t0, t1 = t, t + v["dur"]
        end = t1
        clips = []
        for c in ln["clips"]:
            c0 = end + c.get("gap", 0.25)
            d = len(read_mono(ep / c["file"])) / SR
            clips.append({"file": c["file"], "t0": c0, "t1": c0 + d, "gain": c.get("gain", 0.8)})
            end = c0 + d
        end += ln["after"]
        if ln.get("dur"):
            end = max(end, t0 + ln["dur"])
        words = [{"w": w["w"], "t0": t0 + w["t0"], "t1": t0 + w["t1"]}
                 for w in word_times(ln["caption"], ln["say"], v["dur"], v["runs"])]
        groups = caption_groups(words)
        for i, g in enumerate(groups):
            g1 = groups[i + 1][0]["t0"] - 0.04 if i + 1 < len(groups) else min(t1 + 0.35, end)
            caps.append({"t0": g[0]["t0"] - 0.04, "t1": g1,
                         "words": [{"w": clean_word(w["w"]), "t0": w["t0"]} for w in g]})
        words = [{**w, "w": clean_word(w["w"])} for w in words]
        sfx = []
        for x in ln["sfx"]:
            sfx.append({"type": x["type"], "t": resolve_at(x.get("at", 0), t0, t1, words, clips), "gain": x.get("gain", 0.25)})
        lines.append({"id": ln["id"], "t0": t0, "t1": t1, "end": end, "clips": clips, "sfx": sfx,
                      "words": words})
        t = end
    total = math.ceil((t + TAIL) * fps) / fps
    p = {"title": data["title"], "fps": fps, "total": total, "frames": int(round(total * fps)), "stage": data["stage"],
         "lines": lines, "captions": caps, "bgm": data["bgm"], "waves": data["waves"]}
    (ep / "build" / "plan.json").write_text(json.dumps(p, ensure_ascii=False, indent=1))
    return p


def resolve_at(at, t0: float, t1: float, words: list, clips: list) -> float:
    """줄 안의 시각 표기 → 영상 전체 기준 초.

    숫자: 줄 시작부터 초.  "end": 나레이션이 끝나는 순간.  "end+0.3": 그 0.3초 뒤.
    "w:단어": 그 글자가 든 자막 단어가 나오는 순간.  "w:2": 세 번째 단어.  "clip:0": 첫 클립이 시작하는 순간.
    """
    if isinstance(at, (int, float)):
        return t0 + float(at)
    s = str(at)
    m = re.fullmatch(r"end(?:\+([\d.]+))?", s)
    if m:
        return t1 + float(m.group(1) or 0)
    m = re.fullmatch(r"clip:(\d+)", s)
    if m and int(m.group(1)) < len(clips):
        return clips[int(m.group(1))]["t0"]
    if s.startswith("w:"):
        key = s[2:]
        if key.isdigit() and int(key) < len(words):
            return words[int(key)]["t0"]
        for w in words:
            if key in w["w"]:
                return w["t0"]
    raise ValueError(f"알 수 없는 시각 표기: {at}")


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


def foreground(ep: Path, p: dict) -> tuple[np.ndarray, np.ndarray]:
    """(나레이션+클립+효과음, 배경음을 줄일 구간 마스크)."""
    n = int(round(p["total"] * SR))
    out, duck = np.zeros(n), np.ones(n)

    def add(sig, at, g=1.0):
        i = int(at * SR)
        if i >= n:
            return
        sig = sig[: n - i]
        out[i:i + len(sig)] += g * sig
    for ln in p["lines"]:
        vo = ep / "build" / "vo" / f"{ln['id']}.wav"
        if ln["t1"] > ln["t0"] and vo.is_file():
            add(read_mono(vo), ln["t0"], 0.95)
        for c in ln["clips"]:
            x = read_mono(ep / c["file"])
            add(x / (np.abs(x).max() + 1e-9), c["t0"], c["gain"])
            duck[max(0, int((c["t0"] - 0.1) * SR)):max(0, int((c["t1"] + 0.1) * SR))] = 0.0
        rng = np.random.RandomState(zlib.crc32(ln["id"].encode()) % 2**31)
        for x in ln["sfx"]:
            add(synth_sfx(x["type"], rng), x["t"], x["gain"])
    return out, duck


def bgm_bed(ep: Path, p: dict, n: int) -> np.ndarray:
    b = p["bgm"]
    bed = np.zeros(n)
    t = np.arange(n) / SR
    if b.get("type") == "pad":
        # 낮게 깔리는 화음. 느린 떨림만 있고 박자는 없다.
        for f, g, lfo in ((110.0, 1.0, 0.07), (164.81, 0.6, 0.05), (220.0, 0.45, 0.09), (329.63, 0.2, 0.04)):
            bed += g * np.sin(2 * np.pi * f * t + 0.4 * np.sin(2 * np.pi * 0.31 * t)) * (0.75 + 0.25 * np.sin(2 * np.pi * lfo * t + f))
        bed /= np.abs(bed).max()
    elif b.get("type") == "pulse":
        step = 60 / b.get("bpm", 100)
        x = np.arange(int(0.25 * SR)) / SR
        kick = np.sin(2 * np.pi * (50 + 60 * np.exp(-x * 30)) * x) * np.exp(-x * 14)
        k = 0
        while k * step < p["total"] - 0.8:
            i = int(k * step * SR)
            seg = kick[: max(0, n - i)]
            bed[i:i + len(seg)] += seg
            k += 1
    elif b.get("type") == "file":
        x = read_mono(ep / b["file"])
        bed[: len(x)] = x[:n]
    return bed * np.clip(t / 0.6, 0, 1) * np.clip((p["total"] - t) / 1.0, 0, 1)


def mix(ep: Path, p: dict) -> Path:
    from scipy.ndimage import uniform_filter1d
    fg, duck = foreground(ep, p)
    duck = uniform_filter1d(duck, int(0.08 * SR))
    y = fg + p["bgm"].get("gain", 0.03) * bgm_bed(ep, p, len(fg)) * (0.25 + 0.75 * duck)
    y = y / max(1.0, np.abs(y).max() / 0.97)
    path = ep / "build" / "audio.wav"
    sf.write(path, y, SR)
    return path


def envelope(ep: Path, p: dict) -> list[float]:
    """나레이션+클립+효과음의 프레임별 세기(0~1)."""
    a, _ = foreground(ep, p)
    hop = SR // p["fps"]
    n = p["frames"]
    a = np.pad(a, (0, max(0, n * hop - len(a))))[: n * hop].reshape(n, hop)
    e = np.sqrt((a ** 2).mean(1))
    return [round(float(v), 3) for v in np.clip(e / 0.25, 0, 1)]


def clip_samples(ep: Path, files: list[str]) -> dict:
    out = {}
    for f in dict.fromkeys(files):
        x = read_mono(ep / f, CLIP_SR)
        out[f] = [round(float(v), 3) for v in x / (np.abs(x).max() + 1e-9)]
    return out


# ---------- 렌더 ----------

def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception:
        return pw.chromium.launch(executable_path=FALLBACK_CHROMIUM)


def stage_data(ep: Path, p: dict) -> str:
    files = [c["file"] for ln in p["lines"] for c in ln["clips"]] + p["waves"]
    reel = {"fps": p["fps"], "total": p["total"], "lines": p["lines"], "captions": p["captions"],
            "env": envelope(ep, p), "clips": clip_samples(ep, files), "clip_sr": CLIP_SR}
    return "window.REEL = " + json.dumps(reel, ensure_ascii=False) + ";"


def open_stage(browser, ep: Path, p: dict, init: str):
    page = browser.new_page(viewport={"width": W, "height": H})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(init)
    page.goto((ep / p["stage"]).resolve().as_uri())
    page.evaluate("document.fonts.ready")
    if errors:
        raise SystemExit(f"무대 스크립트 오류: {errors[0]}")
    if not page.evaluate("typeof window.seek === 'function'"):
        raise SystemExit(f"무대가 Reel.stage(...)를 호출하지 않았습니다 ({p['stage']})")
    return page, errors


def render_part(args) -> str:
    ep, p, init, idx, a, b = args
    from playwright.sync_api import sync_playwright
    out = ep / "build" / "parts" / f"{idx:02d}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(p["fps"]),
                           "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
                           "-r", str(p["fps"]), str(out)], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        br = launch(pw)
        page, errors = open_stage(br, ep, p, init)
        for i in range(a, b):
            page.evaluate(f"window.seek({i / p['fps']:.4f})")
            if errors:
                break
            ff.stdin.write(page.screenshot(type="jpeg", quality=95))
        br.close()
    ff.stdin.close()
    ff.wait()
    if errors:
        raise SystemExit(f"무대 스크립트 오류 (t={i / p['fps']:.2f}s): {errors[0]}")
    return str(out)


def render(ep: Path, p: dict) -> Path:
    init = stage_data(ep, p)
    workers = min(4, os.cpu_count() or 1)
    step = math.ceil(p["frames"] / workers)
    jobs = [(ep, p, init, i, a, min(a + step, p["frames"])) for i, a in enumerate(range(0, p["frames"], step))]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        files = list(pool.map(render_part, jobs))
    lst = ep / "build" / "parts.txt"
    lst.write_text("".join(f"file '{Path(f).resolve()}'\n" for f in files))
    video = ep / "build" / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(video)], check=True)
    return video


def shoot(ep: Path, p: dict, times: list[float], out_dir: Path, quality: int = 90) -> list[Path]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    with sync_playwright() as pw:
        br = launch(pw)
        page, errors = open_stage(br, ep, p, stage_data(ep, p))
        for t in times:
            path = out_dir / f"t{t:06.2f}.jpg"
            page.evaluate(f"window.seek({t:.3f})")
            if errors:
                raise SystemExit(f"무대 스크립트 오류 (t={t:.2f}s): {errors[0]}")
            page.screenshot(path=str(path), type="jpeg", quality=quality)
            shots.append(path)
        br.close()
    return shots


def preview(ep: Path, p: dict, cols: int = 6) -> Path:
    """줄마다 2장(나레이션 중간, 줄 끝 직전)을 찍어 한 장으로 붙인다."""
    times = []
    for ln in p["lines"]:
        times += [ln["t0"] + 0.5 * max(ln["t1"] - ln["t0"], 0.1), max(ln["t0"], ln["end"] - 0.08)]
    times.append(p["total"] - 0.05)
    d = ep / "build" / "preview"
    shutil.rmtree(d, ignore_errors=True)
    shots = shoot(ep, p, times, d, quality=80)
    rows = math.ceil(len(shots) / cols)
    out = ep / "build" / "preview.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-pattern_type", "glob", "-i", str(d / "t*.jpg"),
                    "-vf", f"scale=270:-1,tile={cols}x{rows}", "-frames:v", "1", str(out)], check=True)
    print("미리보기 시각(초):", " ".join(f"{t:.1f}" for t in times))
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
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest",
                    "-movflags", "+faststart", str(out)],
                   check=True)
    print(f"완성: {out} ({p['total']:.1f}초, 나레이션 {len(p['lines'])}줄)")
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


def say(text: str, out: Path, voice: dict | None = None) -> None:
    voice = voice or {}
    TTS[tts_backend(voice)](text, voice, out)


_asr = None


def have_asr() -> bool:
    return (MODELS / ASR_MODEL / "small-tokens.txt").is_file()


def hear(x: np.ndarray, lang: str = "ko") -> str:
    """에이전트의 귀. 16 kHz 모노 소리를 받아 적는다."""
    global _asr
    import sherpa_onnx
    if _asr is None:
        if not have_asr():
            raise SystemExit("받아쓰기 모델이 없습니다. `python3 reels/reel.py setup asr`을 먼저 실행하세요.")
        d = MODELS / ASR_MODEL
        _asr = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(d / "small-encoder.int8.onnx"), decoder=str(d / "small-decoder.int8.onnx"),
            tokens=str(d / "small-tokens.txt"), num_threads=4, language=lang, task="transcribe")
    st = _asr.create_stream()
    st.accept_waveform(16000, np.asarray(x, dtype=np.float32))
    _asr.decode_stream(st)
    return st.result.text.strip()


def heard_ratio(heard: str, *wants: str) -> float:
    """받아 적은 글이 대본과 얼마나 같은지(0~1). 글자만 비교한다.
    숫자는 한글로도 아라비아 숫자로도 받아 적히므로, 넘겨준 글(say, caption) 중 가장 가까운 것과 비교한다."""
    def norm(t):
        return re.sub(r"[^0-9A-Za-z가-힣]", "", t)
    return max((difflib.SequenceMatcher(None, norm(w), norm(heard)).ratio() for w in wants if norm(w)), default=0.0)


def listen(target: Path) -> None:
    """소리를 받아 적는다. 에피소드 폴더를 주면 완성 영상을 줄마다 나눠 자막과 나란히 보여 준다."""
    def load(path: Path) -> np.ndarray:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ar", "16000", "-ac", "1", "-f", "f32le", "-"],
                             check=True, capture_output=True).stdout
        return np.frombuffer(raw, dtype=np.float32)

    if target.is_dir():
        p = json.loads((target / "build" / "plan.json").read_text(encoding="utf-8"))
        x = load(target / "out" / f"{target.name}.mp4")
        for ln in p["lines"]:
            a, b = int(max(0, ln["t0"] - 0.1) * 16000), int(ln["end"] * 16000)
            want = " ".join(w["w"] for w in ln["words"]) + (" + 클립" if ln["clips"] else "")
            print(f"{ln['t0']:6.2f}  {ln['id']:<6} 자막: {want}\n{'':15}들림: {hear(x[a:b])}")
    else:
        x = load(target)
        for i in range(0, len(x), 16000 * 12):
            print(f"[{i // 16000:3d}s] {hear(x[i:i + 16000 * 12])}")


def setup(kind: str = "tts") -> None:
    name, url, mark = ((ASR_MODEL, ASR_URL, "small-tokens.txt") if kind == "asr" else (TTS_MODEL, TTS_URL, "tts.json"))
    MODELS.mkdir(exist_ok=True)
    if (MODELS / name / mark).is_file():
        print("이미 있음:", MODELS / name)
        return
    arc = MODELS / "model.tar.bz2"
    print("받는 중:", url)
    urllib.request.urlretrieve(url, arc)
    with tarfile.open(arc) as t:
        t.extractall(MODELS, filter="data")
    arc.unlink()
    print("완료:", MODELS / name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "plan", "preview", "frames", "build", "codec", "say", "listen", "setup"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.cmd == "setup":
        return setup(a.args[0] if a.args else "tts")
    if a.cmd == "listen":
        return listen(Path(a.args[0]))
    if a.cmd == "codec":
        return codec_demo(Path(a.args[0]), Path(a.args[1]))
    if a.cmd == "say":
        return say(a.args[0], Path(a.args[1]), {"sid": int(a.args[2])} if len(a.args) > 2 else None)
    ep = Path(a.args[0])
    if a.cmd == "check":
        errs = check(ep)
        print("통과" if not errs else "문제:\n- " + "\n- ".join(errs))
        sys.exit(1 if errs else 0)
    if a.cmd == "build":
        build(ep)
        return
    data = load_episode(ep)
    p = plan(ep, data, run_tts(ep, data))
    if a.cmd == "plan":
        for ln in p["lines"]:
            print(f"{ln['t0']:6.2f} ~ {ln['end']:6.2f}  {ln['id']:<6} " + " ".join(w["w"] for w in ln["words"]))
        print(f"전체 {p['total']:.1f}초")
    elif a.cmd == "preview":
        print(preview(ep, p))
    elif a.cmd == "frames":
        by_id = {ln["id"]: ln for ln in p["lines"]}
        times = [(by_id[x]["t0"] + by_id[x]["t1"]) / 2 if x in by_id else float(x) for x in a.args[1:]]
        for f in shoot(ep, p, times, ep / "build" / "frames"):
            print(f)


if __name__ == "__main__":
    main()
