"""minimax（minimaxi）后端。

minimax 提供了 Anthropic 兼容端点 https://api.minimaxi.com/anthropic/，
所以我们直接复用 anthropic SDK 调用，但模型名是 minimax 自己的（如 MiniMax-M3）。
"""
from __future__ import annotations

import logging
import re

from app.llm.claude import _parse_script
from app.llm.base import LLMBackend, VideoScript
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class MiniMaxBackend(LLMBackend):
    name = "minimax"

    def __init__(self) -> None:
        from app.config import settings
        from anthropic import Anthropic

        self.api_key = settings.anthropic_api_key
        self.base_url = settings.anthropic_base_url
        if not self.api_key:
            raise RuntimeError("缺少 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN")
        if not self.base_url:
            raise RuntimeError("minimax 后端需要 ANTHROPIC_BASE_URL（指向 https://api.minimaxi.com/anthropic/）")
        self.client = Anthropic(api_key=self.api_key, base_url=self.base_url)
        self.model = settings.anthropic_model
        logger.info("MiniMax backend ready, model=%s", self.model)

    def summarize_to_script(
        self,
        title: str,
        author: str,
        body: str,
        target_seconds: int = 75,
    ) -> VideoScript:
        # minimax 强推理模型会做深度 thinking，max_tokens 要留足空间
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_user_prompt(title, author, body, target_seconds),
                }
            ],
        )
        # 收集所有 text 块（跳 thinking 块）
        text_parts = [
            b.text
            for b in msg.content
            if getattr(b, "type", None) == "text" and b.text
        ]
        raw = "".join(text_parts).strip()
        if not raw:
            thinking_len = sum(
                len(getattr(b, "thinking", "") or "")
                for b in msg.content
                if getattr(b, "type", None) == "thinking"
            )
            stop = getattr(msg, "stop_reason", "?")
            logger.warning(
                "minimax returned no text (thinking_len=%d, stop_reason=%s)", thinking_len, stop
            )
            raise RuntimeError(
                f"minimax 未返回文本（可能 thinking 耗尽 token）。stop_reason={stop}"
            )
        return _parse_script(raw)
