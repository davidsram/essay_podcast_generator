"""合成 5 段水墨视频 BGM（60s，纯 ffmpeg lavfi，零外部依赖）。

每段 60 秒、44.1kHz 单声道 mp3 写到 assets/music/，对应 `_pick_music` 随机池。
- ancient_guqin   : 古琴 5 声音阶 (CDEGA) 缓慢琶音
- flute_distant   : 笛/箫长音，缓 vibrato
- piano_minimal   : 极简钢琴进行 (C-Am-F-G)
- ambient_pad     : 三和弦长 pad，缓慢包络
- rain_white_noise: 白噪音底层 + 偶发"雨点"
"""
from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = ROOT / "assets" / "music"

DURATION = 60.0
SR = 44100
N = int(SR * DURATION)


# === wav 写盘辅助（沿用 generate_assets.py 的实现） ===

def _write_wav_from_samples(samples: list[float], out_wav: Path) -> None:
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        for v in samples:
            v = max(-0.9, min(0.9, v))
            frames += struct.pack("<h", int(v * 32767))
        w.writeframes(bytes(frames))


def _wav_to_mp3(wav: Path) -> Path:
    mp3 = wav.with_suffix(".mp3")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(wav),
            "-c:a", "libmp3lame", "-q:a", "5",
            str(mp3),
        ],
        check=True, capture_output=True,
    )
    wav.unlink()
    return mp3


# === 1) ancient_guqin 古琴 5 声音阶（C D E G A）===

def render_ancient_guqin() -> Path:
    """5 声音阶 CDEGA 缓慢琶音，每音 ~5s 带衰减。"""
    freqs = [261.63, 293.66, 329.63, 392.00, 440.00]  # C4 D4 E4 G4 A4
    note_dur = 4.5  # 每音持续 4.5s
    pause_dur = 0.5
    cycle = note_dur + pause_dur
    samples = [0.0] * N
    cycle_start = 0.0
    note_idx = 0
    while cycle_start < DURATION:
        f = freqs[note_idx % len(freqs)]
        start = int(cycle_start * SR)
        # 每音起音 0.05s，余下为指数衰减
        n_note = int(note_dur * SR)
        attack = int(0.05 * SR)
        for j in range(n_note):
            if start + j >= N:
                break
            t = j / SR
            env = math.exp(-t * 0.4)  # 缓慢衰减
            if j < attack:
                env *= j / attack
            v = 0.25 * env * math.sin(2 * math.pi * f * t)
            # 二次谐波（古琴音色）
            v += 0.08 * env * math.sin(2 * math.pi * f * 2 * t)
            samples[start + j] += v
        cycle_start += cycle
        note_idx += 1
    # 全局淡入淡出 1.5s
    for i in range(int(1.5 * SR)):
        samples[i] *= i / (1.5 * SR)
        samples[-(i + 1)] *= i / (1.5 * SR)
    out_wav = MUSIC_DIR / "ancient_guqin.wav"
    _write_wav_from_samples(samples, out_wav)
    return _wav_to_mp3(out_wav)


# === 2) flute_distant 笛/箫长音 ===

def render_flute_distant() -> Path:
    """两条 sine 略 detune，缓 vibrato，长音 60s。"""
    base = 587.33  # D5
    overtone = 880.0  # A5（八度）
    samples: list[float] = []
    for i in range(N):
        t = i / SR
        # 缓 vibrato（5Hz, ±5 cents）
        vib = 1.0 + 0.003 * math.sin(2 * math.pi * 0.3 * t)
        v = 0.18 * math.sin(2 * math.pi * base * vib * t)
        v += 0.08 * math.sin(2 * math.pi * overtone * vib * t)
        # 整体长包络：缓慢呼吸（5s 周期）
        breath = 0.7 + 0.3 * math.sin(2 * math.pi * 0.2 * t)
        samples.append(v * breath)
    # 头尾淡入淡出 3s
    for i in range(int(3 * SR)):
        samples[i] *= i / (3 * SR)
        samples[-(i + 1)] *= i / (3 * SR)
    out_wav = MUSIC_DIR / "flute_distant.wav"
    _write_wav_from_samples(samples, out_wav)
    return _wav_to_mp3(out_wav)


# === 3) piano_minimal 极简钢琴（C-Am-F-G）===

def render_piano_minimal() -> Path:
    """每 6s 一个三和弦，模拟钢琴衰减。"""
    chords = [
        (261.63, 329.63, 392.00),  # C
        (220.00, 261.63, 329.63),  # Am
        (174.61, 220.00, 261.63),  # F
        (196.00, 246.94, 293.66),  # G
    ]
    chord_dur = 6.0
    samples = [0.0] * N
    t0 = 0.0
    idx = 0
    while t0 < DURATION:
        chord = chords[idx % len(chords)]
        start = int(t0 * SR)
        n = int(chord_dur * SR)
        for j in range(n):
            if start + j >= N:
                break
            tt = j / SR
            env = math.exp(-tt * 0.3)  # 钢琴衰减
            v = 0.0
            for f in chord:
                v += 0.10 * env * math.sin(2 * math.pi * f * tt)
            samples[start + j] += v
        t0 += chord_dur
        idx += 1
    # 头尾淡入淡出 2s
    for i in range(int(2 * SR)):
        samples[i] *= i / (2 * SR)
        samples[-(i + 1)] *= i / (2 * SR)
    out_wav = MUSIC_DIR / "piano_minimal.wav"
    _write_wav_from_samples(samples, out_wav)
    return _wav_to_mp3(out_wav)


# === 4) ambient_pad 氛围长 pad ===

def render_ambient_pad() -> Path:
    """三 sine 长 pad（220/330/440），极缓包络。"""
    freqs = [220.0, 330.0, 440.0]
    samples: list[float] = []
    for i in range(N):
        t = i / SR
        # 整体长包络：10s 起，10s 落
        if t < 10:
            env = t / 10
        elif t > DURATION - 10:
            env = (DURATION - t) / 10
        else:
            env = 1.0
        v = 0.0
        for f in freqs:
            v += 0.10 * env * math.sin(2 * math.pi * f * t)
        # 微微 detune 慢漂
        v += 0.05 * env * math.sin(2 * math.pi * (440 + 1.5 * math.sin(0.1 * t)) * t)
        samples.append(v)
    out_wav = MUSIC_DIR / "ambient_pad.wav"
    _write_wav_from_samples(samples, out_wav)
    return _wav_to_mp3(out_wav)


# === 5) rain_white_noise 雨声 + 偶发雨点 ===

def render_rain_white_noise() -> Path:
    """白噪音底层（音量极低）+ 偶发高频 sine 模拟雨点。"""
    import random
    rng = random.Random(2026)
    samples: list[float] = []
    # 预生成雨点时间表（每 0.3-1.2s 一滴）
    drops: list[tuple[int, float]] = []
    t = 0.5
    while t < DURATION:
        f = rng.uniform(2500, 4500)  # 雨点频率
        drops.append((int(t * SR), f))
        t += rng.uniform(0.3, 1.2)
    for i in range(N):
        t = i / SR
        # 底层白噪音
        v = 0.04 * (rng.random() * 2 - 1)
        # 雨点（短促 sine + 快速衰减）
        for start, f in drops:
            dt = t - start / SR
            if 0 <= dt < 0.08:
                env = math.exp(-dt * 60)
                v += 0.12 * env * math.sin(2 * math.pi * f * dt)
        samples.append(v)
    # 头尾淡入淡出 2s
    for i in range(int(2 * SR)):
        samples[i] *= i / (2 * SR)
        samples[-(i + 1)] *= i / (2 * SR)
    out_wav = MUSIC_DIR / "rain_white_noise.wav"
    _write_wav_from_samples(samples, out_wav)
    return _wav_to_mp3(out_wav)


# === 入口 ===

_RENDERERS = [
    render_ancient_guqin, render_flute_distant, render_piano_minimal,
    render_ambient_pad, render_rain_white_noise,
]


def main() -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for fn in _RENDERERS:
        p = fn()
        print(f"[bgm] {fn.__name__:<22} -> {p}  ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
