"""配置加载。

优先级：.env 显式设置 > 系统环境变量
（读系统 env 是为了复用 Claude Code 已经在用的 minimax 代理）
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765

    # LLM — 优先 .env，再 fallback 到 Claude Code 已经在用的 minimax 代理
    anthropic_api_key: str = field(
        default_factory=lambda: _env("ANTHROPIC_API_KEY") or _env("ANTHROPIC_AUTH_TOKEN")
    )
    anthropic_base_url: str = field(
        default_factory=lambda: _env("ANTHROPIC_BASE_URL")
    )
    anthropic_model: str = field(
        default_factory=lambda: _env("ANTHROPIC_MODEL") or _env("ANTHROPIC_DEFAULT_MODEL") or "claude-sonnet-4-6"
    )

    # WeChat
    wechat_account: str = field(default_factory=lambda: _env("WECHAT_ACCOUNT", "援翰写心"))
    wechat_search_engine: str = field(default_factory=lambda: _env("WECHAT_SEARCH_ENGINE", "sogou"))

    # Video
    video_width: int = int(_env("VIDEO_WIDTH", "1080"))
    video_height: int = int(_env("VIDEO_HEIGHT", "1920"))
    video_duration: int = int(_env("VIDEO_DURATION", "75"))
    # Ken Burns 慢速放大（5% zoompan）。默认 False——ffmpeg zoompan 是 CPU 重活，
    # 10 段 30s 视频全 30fps 渲染要 30+ 分钟。生产需要时设 VIDEO_KEN_BURNS=1。
    video_ken_burns: bool = _env("VIDEO_KEN_BURNS", "0") not in {"0", "", "false", "False"}
    # 背景图氛围处理（模糊 + 降饱和 + 米色蒙版 + 暗角），默认开启。
    # 让真摄影图退成"染纸黄的氛围底"，跟字共处舒服。BG_TREATMENT=0 关掉做对比。
    bg_treatment_enabled: bool = _env("BG_TREATMENT", "1") not in {"0", "", "false", "False"}
    tts_voice: str = field(
        default_factory=lambda: _env("TTS_VOICE") or ""
    )
    tts_rate: str = _env("TTS_RATE", "-8%")

    # Paths
    asset_bg_dir: Path = field(default_factory=lambda: ROOT / _env("ASSET_BG_DIR", "assets/backgrounds"))
    asset_music_dir: Path = field(default_factory=lambda: ROOT / _env("ASSET_MUSIC_DIR", "assets/music"))
    output_dir: Path = field(default_factory=lambda: ROOT / _env("OUTPUT_DIR", "output"))
    data_dir: Path = field(default_factory=lambda: ROOT / "data")

    # Pexels（段落级搜图；空则跳过搜图链路，走 LLM 选图）
    pexels_api_key: str = field(default_factory=lambda: _env("PEXELS_API_KEY"))

    def __post_init__(self) -> None:
        for d in (self.asset_bg_dir, self.asset_music_dir, self.output_dir, self.data_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
