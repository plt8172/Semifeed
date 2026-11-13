#!/usr/bin/env python3
"""이 에피소드의 데모 소리를 만든다: python3 reels/episodes/timer-interrupt/make_audio.py

CPU 코어 하나에서 '음악 앱'과 '무거운 앱'이 번갈아 도는 것을 흉내 내고(simulate), 음악 앱이 미리 만들어 둔 소리가
남아 있을 때만 음악이 들리게 한다. 그래서 들리는 소리는 시뮬레이션 결과 그 자체다.

audio/r1.wav  타이머 없음: 음악만 돌다가 1.3초에 무거운 앱을 켠다. 무거운 앱이 CPU를 놓지 않아 음악이 멈춘다
audio/r2.wav  타이머가 0.1초마다 CPU를 멈춰 세운다: 음악 앱 차례가 늦게 와서 소리가 뚝뚝 끊긴다
audio/r3.wav  타이머가 0.004초마다(1초에 250번) 멈춰 세운다: 끊기지 않는다

시뮬레이션 규칙과 수치(BUF, WAKE, WORK, DT, 라운드 설정)는 stage.html이 화면에 그리는 것과 같다. 한쪽을 바꾸면 다른 쪽도 바꾼다.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
SR = 24000

BUF = 0.04      # 음악 앱이 한 번에 미리 만들어 두는 소리의 길이 (초)
WAKE = 0.5      # 만들어 둔 소리가 이만큼(비율) 남으면 음악 앱이 다시 CPU를 원한다
WORK = 0.002    # 음악 앱이 소리를 채우는 데 쓰는 CPU 시간 (초)
DT = 0.0005     # 시뮬레이션 한 걸음 (초)

# 라운드: (길이, 타이머 간격 또는 None, 무거운 앱을 켜는 시각)
ROUNDS = {
    "r1": (2.0, None, 1.3),
    "r2": (2.0, 0.1, 0.0),
    "r3": (2.0, 0.004, 0.0),
}


def simulate(dur: float, tick, hog_at: float):
    """DT 간격으로 [누가 CPU를 쓰는지(0 쉼, 1 음악 앱, 2 무거운 앱), 남은 소리(초)]를 돌려준다.
    타이머가 울리면(tick초마다) 지금 돌던 앱을 멈추고, 기다리던 앱이 있으면 그 앱으로 넘긴다.
    타이머가 없으면 무거운 앱은 CPU를 스스로 놓지 않는다. 음악 앱은 소리를 채우면 스스로 놓는다."""
    n = int(round(dur / DT))
    who, level = np.zeros(n, dtype=np.int8), np.zeros(n)
    buf, run, work, wants = BUF, 1, 0.0, True
    next_tick = tick if tick else None
    for i in range(n):
        t = i * DT
        if not wants and buf <= WAKE * BUF + 1e-9:
            wants = True
        hog = t >= hog_at - 1e-9
        if next_tick is not None and t >= next_tick - 1e-9:      # 타이머 인터럽트
            next_tick += tick
            if run == 2 and wants:
                run, work = 1, 0.0
        if run == 0:
            if wants:
                run, work = 1, 0.0
            elif hog:
                run = 2
        who[i], level[i] = run, buf
        buf = max(0.0, buf - DT)
        if run == 1:
            work += DT
            if work >= WORK - 1e-9:                             # 다 채웠으면 스스로 놓는다
                buf, wants = BUF, False
                run = 2 if hog else 0
    return who, level


def melody(dur: float) -> np.ndarray:
    """음악 앱이 트는 짧은 곡: 오르골 같은 음 + 낮은 음."""
    t = np.arange(int(dur * SR)) / SR
    notes = [76, 79, 81, 84, 81, 79, 76, 74, 76, 79, 81, 79, 76, 74, 72, 74]       # MIDI
    bass = [48, 48, 45, 45]
    y = np.zeros_like(t)
    step = 0.15
    for k, m in enumerate(notes * 2):
        a = k * step
        if a >= dur:
            break
        f = 440 * 2 ** ((m - 69) / 12)
        u = t - a
        env = np.where(u >= 0, (1 - np.exp(-u / 0.006)) * np.exp(-u / 0.45), 0)
        y += env * (np.sin(2 * np.pi * f * u) + 0.25 * np.sin(4 * np.pi * f * u) + 0.08 * np.sin(6 * np.pi * f * u))
    for k, m in enumerate(bass * 4):
        a = k * step * 4
        if a >= dur:
            break
        f = 440 * 2 ** ((m - 69) / 12)
        u = t - a
        env = np.where(u >= 0, (1 - np.exp(-u / 0.01)) * np.exp(-u / 0.8), 0)
        y += 0.6 * env * (np.sin(2 * np.pi * f * u) + 0.3 * np.sin(4 * np.pi * f * u))
    return y / np.abs(y).max() * 0.8


def render(name: str) -> np.ndarray:
    dur, tick, hog_at = ROUNDS[name]
    who, level = simulate(dur, tick, hog_at)
    on = np.repeat((level > 0).astype(float), int(round(DT * SR)))
    on = np.pad(on, (0, max(0, int(dur * SR) - len(on))))[: int(dur * SR)]
    k = int(0.0015 * SR)                                         # 끊기는 곳에 1.5ms 페이드 (딸깍 소리 줄이기)
    gate = np.convolve(on, np.ones(k) / k, mode="same")
    return melody(dur) * gate


def main() -> None:
    out = HERE / "audio"
    out.mkdir(exist_ok=True)
    for name in ROUNDS:
        y = render(name)
        sf.write(out / f"{name}.wav", y, SR)
        dur, tick, hog_at = ROUNDS[name]
        who, level = simulate(dur, tick, hog_at)
        print(f"{name}: 소리 나는 비율 {np.mean(level > 0):.2f}, 음악 앱이 CPU를 쓴 비율 {np.mean(who == 1):.3f}")


if __name__ == "__main__":
    main()
