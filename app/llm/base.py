"""LLM 抽象层：可插拔的多后端。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ScriptSegment:
    """一段口播文案。"""

    text: str
    """口播文本（用于 TTS）"""
    visual_hint: str = ""
    """视觉提示：背景意象（用于配图选择）"""
    duration_hint: float = 0.0
    """建议时长（秒），0 表示由合成器自动估算"""


@dataclass
class VideoScript:
    """整支视频的脚本。"""

    title: str
    """视频标题（封面/片头用）"""
    subtitle: str
    """副标题"""
    author: str
    """原作者署名（公众号作者）"""
    segments: list[ScriptSegment]
    """逐段口播"""
    closing: str
    """片尾一句话"""

    @property
    def full_text(self) -> str:
        return "".join(seg.text for seg in self.segments) + self.closing


class LLMBackend(ABC):
    """LLM 后端抽象接口。"""

    name: str = "base"

    @abstractmethod
    def summarize_to_script(
        self,
        title: str,
        author: str,
        body: str,
        target_seconds: int = 75,
    ) -> VideoScript:
        """把文章正文转为视频脚本。"""


def get_backend(name: str | None = None) -> LLMBackend:
    """根据名称取后端实例。"""
    from app.llm.claude import ClaudeBackend
    from app.llm.minimax import MiniMaxBackend
    from app.llm.mock import MockBackend

    name = (name or "claude").lower()
    if name == "claude":
        return ClaudeBackend()
    if name == "minimax":
        return MiniMaxBackend()
    if name == "mock":
        return MockBackend()
    raise ValueError(f"未实现的 LLM 后端: {name}")
