"""LLM 解析段落 + Pexels 搜图编排。

调用流：
1. LLM 一次性把全部 visual_hint 扩成 1-3 个英文 Pexels 搜索词
2. 每个 hint 用第一个搜索词去 Pexels 搜；失败试 fallback_queries
3. 返回 {hint: (path, photo_meta) | None}，None 时 caller 走 LLM 选图

失败软降级（不抛、不破整支视频）：
- LLM 失败 → 用 hint 原文中匹配出的英文词
- Pexels 失败 / 搜不到 → 返回 None
- 整条链路视作 hint→None 映射
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from anthropic import Anthropic

from app.video.pexels_client import PexelsClient

logger = logging.getLogger(__name__)


_EXPAND_SYSTEM_PROMPT = """你是一个视频分镜师。我会给你几段视频的视觉提示词和对应的口播正文。
请为每段扩展 1-3 个英文 Pexels 搜索词。

要求：
- 理解正文的完整语义——不仅是关键词，而是场景、人物关系、情绪、氛围
- 提取核心场景：主体（几人/谁）+ 动作 + 地点 + 天气/光照/情绪
- 用具体名词（避免抽象词如 "beautiful"）
- 多角度：候选词可换拍摄角度、镜头距离、风格

返回格式（严格 JSON，不要任何解释）：
{"queries": {"提示词1": ["term1", "term2"], "提示词2": ["term1"], ...}}"""


def expand_hints(
    hints: list[str],
    *,
    texts: list[str] | None = None,
    client: Anthropic,
    model: str,
) -> dict[str, list[str]]:
    """LLM 一次性把全部 hints 扩成英文搜索词列表。失败返回 {}。

    texts 可选：每段的口播正文。传了则附在每个 hint 下方，让 LLM 理解完整语境
    （比如"围炉剪影"是朋友聚会还是情侣独处）。不传时退到只看 visual_hint。
    """
    if not hints:
        return {}

    lines: list[str] = []
    for i, h in enumerate(hints):
        lines.append(f"{i+1}. {h}")
        if texts and i < len(texts) and texts[i].strip():
            lines.append(f"   正文：{texts[i].strip()[:120]}")
    body = "\n".join(lines)

    user_prompt = f"""视觉提示词与正文：
{body}

请为每段扩展 1-3 个英文 Pexels 搜索词。返回 JSON。"""

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_EXPAND_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception:
        logger.warning("expand_hints: LLM 调用失败", exc_info=True)
        return {}

    text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    raw = "".join(text_parts)
    if not raw.strip():
        return {}

    # 剥 code fence
    raw = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("expand_hints: JSON 解析失败 raw=%s", raw[:200])
        return {}

    queries = data.get("queries")
    if not isinstance(queries, dict):
        return {}

    # 归一化：每个 hint 必须是 list[str]
    result: dict[str, list[str]] = {}
    for hint, qs in queries.items():
        if isinstance(qs, str):
            result[hint] = [qs]
        elif isinstance(qs, list):
            result[hint] = [q for q in qs if isinstance(q, str) and q.strip()][:3]
        if hint in result and not result[hint]:
            result[hint] = [_tokenize_fallback(hint)]
    return result


_CN_TO_EN_MINI: dict[str, str] = {
    "雪": "snow", "夜": "night", "车站": "station", "火车站": "train station",
    "站台": "platform", "风": "wind", "寒": "cold", "烛": "candle", "灯": "light",
    "晨": "morning", "雾": "fog", "街": "street", "书": "book", "信": "letter",
    "人": "person", "炉": "fireplace", "杯": "cup", "窗": "window",
    "山": "mountain", "海": "ocean", "雨": "rain", "月": "moon",
    "古": "ancient", "桥": "bridge", "船": "boat", "花": "flower",
    "木": "wood", "林": "forest", "路": "road", "塔": "tower",
    "城": "city", "家": "home", "茶": "tea", "酒": "wine",
}


def _tokenize_fallback(hint: str) -> str:
    """LLM 失败时，从 hint 原文里抽英文/拉丁词 + 中英映射表，凑一个搜索词。"""
    # 1) 抽 hint 里已有的英文/拉丁词
    latin = re.findall(r"[A-Za-z][A-Za-z\s]{2,}", hint)
    if latin:
        return latin[0].strip().lower()
    # 2) 中文 token → 翻译
    tokens: list[str] = []
    for cn, en in _CN_TO_EN_MINI.items():
        if cn in hint:
            tokens.append(en)
    if tokens:
        return " ".join(tokens[:3])
    # 3) 实在没有 → 用原 hint（utf-8 编码 Pexels 也能搜）
    return hint


class PhotoSearcher:
    """编排：LLM expand + Pexels get_or_download，返回 hint→(Path, meta) 映射。"""

    def __init__(self, pexels: PexelsClient, *, client: Anthropic, model: str) -> None:
        self.pexels = pexels
        self.client = client
        self.model = model

    def fetch_all(
        self, hints: list[str], *, texts: list[str] | None = None,
    ) -> dict[str, tuple[Path, dict] | None]:
        """对每个 hint：LLM 扩词 → Pexels 搜 → 缓存下载。失败返 None。

        texts 可选：每段口播正文，传给 expand_hints 让 LLM 理解完整语境。
        """
        if not hints:
            return {}

        queries = expand_hints(
            hints, texts=texts, client=self.client, model=self.model,
        )

        result: dict[str, tuple[Path, dict] | None] = {}
        for hint in hints:
            terms = queries.get(hint) or [_tokenize_fallback(hint)]
            primary = terms[0]
            fallbacks = terms[1:] + [_tokenize_fallback(hint)]
            # 去重保序
            seen = {primary}
            fallbacks = [f for f in fallbacks if f not in seen and not seen.add(f)]
            try:
                result[hint] = self.pexels.get_or_download(
                    primary, fallback_queries=fallbacks
                )
            except Exception:
                logger.warning("PhotoSearcher: hint=%r 全失败", hint, exc_info=True)
                result[hint] = None
        return result
