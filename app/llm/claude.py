"""Claude 后端实现。"""
from __future__ import annotations

import json
import re

from anthropic import Anthropic

from app.config import settings
from app.llm.base import LLMBackend, ScriptSegment, VideoScript
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt


def _strip_code_fence(text: str) -> str:
    """剥掉模型可能输出的 ```json ... ``` 包裹。"""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _parse_script(raw: str) -> VideoScript:
    raw = _strip_code_fence(raw)
    data = json.loads(raw)
    segs = [
        ScriptSegment(
            text=str(s.get("text", "")).strip(),
            visual_hint=str(s.get("visual_hint", "")).strip(),
            duration_hint=float(s.get("duration_hint", 0) or 0),
        )
        for s in data.get("segments", [])
        if str(s.get("text", "")).strip()
    ]
    if not segs:
        raise ValueError("LLM 输出未包含任何 segments")
    return VideoScript(
        title=str(data.get("title", "")).strip() or "无题",
        subtitle=str(data.get("subtitle", "")).strip(),
        author=str(data.get("author", "")).strip(),
        segments=segs,
        closing=str(data.get("closing", "")).strip(),
    )


class ClaudeBackend(LLMBackend):
    name = "claude"

    def __init__(self) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "未配置 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN。\n"
                "方案 1：在 .env 里设置 ANTHROPIC_API_KEY=...\n"
                "方案 2：复用 Claude Code 的 env（ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL/ANTHROPIC_MODEL）"
            )
        # 构造 client
        # - 有 base_url（minimax 代理）：用 api_key（SDK 会发 X-Api-Key 头，代理期望这个）
        # - 无 base_url（直连 Anthropic）：用 api_key
        client_kwargs: dict = {"api_key": settings.anthropic_api_key}
        if settings.anthropic_base_url:
            client_kwargs["base_url"] = settings.anthropic_base_url
        self.client = Anthropic(**client_kwargs)
        self.model = settings.anthropic_model

    def summarize_to_script(
        self,
        title: str,
        author: str,
        body: str,
        target_seconds: int = 75,
    ) -> VideoScript:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_user_prompt(title, author, body, target_seconds),
                }
            ],
        )
        # 拼接所有 text 块
        text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        raw = "".join(text_parts)
        return _parse_script(raw)
