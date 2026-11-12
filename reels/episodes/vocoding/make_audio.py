#!/usr/bin/env python3
"""이 에피소드의 데모 음성을 만든다: python3 reels/episodes/vocoding/make_audio.py

audio/buzz.wav  성대 떨림만 (입 모양 없음)
audio/a.wav     같은 떨림에 '아' 입 모양(공명)을 씌운 소리
audio/ai.wav    떨림은 그대로 두고 입 모양만 '아'에서 '이'로 바꾼 소리
audio/A·B·C.wav 같은 문장을 전화 PCM(64k)·GSM(13k)·Codec2(700bps)로 보냈다 복원한 소리

성대·입 모양 합성식과 수치(F0, FORMANTS, GLIDE)는 stage.html이 화면에 그리는 것과 같다. 한쪽을 바꾸면 다른 쪽도 바꾼다.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import reel  # noqa: E402

SR = 16000
F0 = 120.0
# (공명 주파수 Hz, 대역폭 Hz, 세기)
FORMANTS = {
    "a": [(800, 80, 1.0), (1200, 90, 0.6), (2500, 120, 0.25)],
    "i": [(280, 60, 1.0), (2250, 100, 0.6), (2900, 120, 0.4)],
}
GLIDE = (0.5, 0.25, 0.6)      # ai.wav: '아' 유지, 바뀌는 시간, '이' 유지 (초)
N = int(0.03 * SR)
T = np.arange(N) / SR


def response(mix: float) -> np.ndarray:
    """입 모양이 '아'(mix=0)에서 '이'(mix=1) 사이일 때, 성대 떨림 한 번에 대한 울림."""
    out = np.zeros(N)
    for (f0, b0, a0), (f1, b1, a1) in zip(FORMANTS["a"], FORMANTS["i"]):
        f, b, a = f0 + (f1 - f0) * mix, b0 + (b1 - b0) * mix, a0 + (a1 - a0) * mix
        out += a * np.exp(-np.pi * b * T) * np.sin(2 * np.pi * f * T)
    return out


def buzz() -> np.ndarray:
    return np.exp(-2500 * T) - np.exp(-9000 * T)


def voice(shape, dur: float) -> np.ndarray:
    """shape(t) → 그 순간의 울림. 성대는 F0로 일정하게(살짝 내려가며) 떤다."""
    y = np.zeros(int(dur * SR) + N)
    t = 0.0
    while t < dur:
        i = int(t * SR)
        y[i:i + N] += shape(t)
        t += 1 / (F0 * (1.03 - 0.08 * t / dur))
    y = y[: int(dur * SR)]
    k = np.arange(len(y))
    y *= np.clip(np.minimum(k, len(y) - k) / (0.05 * SR), 0, 1)
    return y / np.abs(y).max() * 0.8


def glide_mix(t: float) -> float:
    m = min(max((t - GLIDE[0]) / GLIDE[1], 0.0), 1.0)
    return m * m * (3 - 2 * m)


def main() -> None:
    out = HERE / "audio"
    out.mkdir(exist_ok=True)
    sf.write(out / "buzz.wav", voice(lambda t: buzz(), 0.9), SR)
    sf.write(out / "a.wav", voice(lambda t: response(0.0), 0.9), SR)
    sf.write(out / "ai.wav", voice(lambda t: response(glide_mix(t)), sum(GLIDE)), SR)
    # 통화 상대의 목소리: 나레이션(2번)과 구별되고, 화면의 성대 떨림(120 Hz)과 높이가 비슷한 낮은 목소리(7번).
    # 내장 TTS는 읽을 때마다 조금씩 다르다. 가장 많이 줄인 C까지 그대로 받아 적히는 것이 나올 때까지 다시 만든다.
    # 대본이 "90분의 1인데도 알아들을 수 있다"고 말하기 때문이다. 커밋된 A·B·C는 그렇게 확인한 한 벌이다.
    src, said = out / "_src.wav", "내 목소리 잘 들려?"
    for _ in range(8):
        reel.say(said, src, {"backend": "local", "sid": 7, "speed": 1.3})
        reel.codec_demo(src, out)
        heard = [reel.hear(reel.read_mono(out / f"{n}.wav", 16000)) for n in "ABC"]
        print("받아쓰기:", heard)
        if all(reel.heard_ratio(h, said) == 1 for h in heard):
            break
    else:
        print("경고: C가 그대로 받아 적히는 음성을 만들지 못했습니다. 문장을 바꾸세요.")
    src.unlink()


if __name__ == "__main__":
    main()
