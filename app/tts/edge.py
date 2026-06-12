"""Edge TTS 封装。"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

import edge_tts

from app.config import settings


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
    asyncio.run(_synthesize_async(text, out_path, settings.tts_voice, settings.tts_rate))
    return _ffprobe_duration(out_path)


def synth_full(text: str, out_path: Path) -> float:
    """合成整段文本，返回总时长（秒）。"""
    return synth_segment(text, out_path)
