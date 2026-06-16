"""Edge TTS 封装。"""
from __future__ import annotations

import asyncio
import hashlib
import random
import subprocess
from pathlib import Path

import edge_tts

from app.config import settings

# 中文 Edge TTS 声音池（一个视频随机抽一个，.env 设 TTS_VOICE 可固定）
_CN_VOICES = [
    "zh-CN-XiaoxiaoNeural",   # 女声 温柔（默认）
    "zh-CN-XiaoyiNeural",     # 女声 甜美
    "zh-CN-YunjianNeural",    # 男声 深沉
    "zh-CN-YunxiNeural",      # 男声 标准
    "zh-CN-YunxiaNeural",     # 男声 年轻
    "zh-CN-YunyangNeural",    # 男声 新闻感
]


def _pick_voice() -> str:
    """选声音：.env 显式设了 TTS_VOICE 则用；否则从池里随机抽一个。

    每次调用随机抽，确保不同视频可能不同声线。
    """
    explicit = settings.tts_voice
    if explicit:
        return explicit
    return random.choice(_CN_VOICES)


def _ffprobe_duration(path: Path) -> float:
    """用 ffprobe 取 mp3 时长（秒）。"""
    import json
    import subprocess

    out = subprocess.check_output(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
    )
    data = json.loads(out)
    return float(data["format"]["duration"])


async def _synthesize_async(text: str, out_path: Path, voice: str, rate: str) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(out_path))


def synth_segment(text: str, out_path: Path) -> float:
    """合成单段，返回时长（秒）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    voice = _pick_voice()
    asyncio.run(_synthesize_async(text, out_path, voice, settings.tts_rate))
    return _ffprobe_duration(out_path)


def synth_full(text: str, out_path: Path) -> float:
    """合成整段文本，返回总时长（秒）。"""
    return synth_segment(text, out_path)
