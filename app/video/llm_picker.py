"""LLM 语义选图：一次 API 调用为全部 visual_hint 选最匹配的照片。

替代 BG_KEYWORDS longest-match，能理解场景语义（"站台"→城市街景不是雪山）。
失败软降级返回 {} → caller 走 keyword fallback。
"""
from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_PICK_SYSTEM_PROMPT = """你是一个视频配图助手。你会收到几段视频的"视觉提示词"和一个候选照片库。
请为每个提示词选出最匹配的照片。如果候选库里没有合适的照片，返回 null。

规则：
- 理解提示词的完整语义——不仅是关键词，而是场景、情绪、氛围
- 优先匹配场景类型（如"站台"→城市/街景/交通，不是山/水/森林；"炉火"→室内/暖光/烛光，不是户外）
- 提示词里如有地域暗示（如"华沙/莫斯科/江南"等城市名），与该城市匹配的图优先；但纯场景/纯情绪的提示词（烛光、晨雾、静物）不应被地域偏好覆盖
- 文章背景信息里给的地域标签是软信号，作用同上
- 没有合适的就返回 null，不要勉强
- 同一张照片可以被多个提示词选中（不要求去重）

返回格式（严格 JSON，不要任何解释或多余文字）：
{"picks": {"提示词1": "photo_key", "提示词2": null, ...}}"""


def build_pick_prompt(
    hints: list[str],
    pool_keys: list[str],
    manifest: dict,
    location_hint: list[str] | None = None,
) -> str:
    """构造 prompt：列出所有视觉提示 + 候选图元数据 + 地域软信号。"""
    hint_lines = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hints))

    photo_lines: list[str] = []
    for k in pool_keys:
        meta = manifest.get(k, {})
        caption = meta.get("caption_hint", "")
        scene = meta.get("scene", [])
        location = meta.get("location", [])
        tags = scene + location
        tag_str = ", ".join(tags) if tags else ""
        photo_lines.append(f"- {k}: {caption}" + (f" [{tag_str}]" if tag_str else ""))

    photo_list = "\n".join(photo_lines)

    location_line = ""
    if location_hint:
        location_line = f"\n\n背景信息：这篇文章发生在 {', '.join(location_hint)}。地域匹配的图（如该国/该城的照片）应优先选，但若提示词描述的是通用场景（室内、烛光、静物等），可以选择通用图。\n"

    return f"""视觉提示词：
{hint_lines}
{location_line}
候选照片库：
{photo_list}

请为每个提示词选出最匹配的照片。返回 JSON：{{"picks": {{"提示词1": "photo_key", "提示词2": null, ...}}}}"""


def parse_pick_response(raw: str, pool_keys: set[str]) -> dict[str, str | None]:
    """解析 LLM 返回的 JSON → {hint: photo_key | null}。

    校验：photo_key 必须在 pool_keys 中，否则视为 null。
    解析失败返回 {}（caller 走 keyword fallback）。
    """
    raw = raw.strip()
    # 剥 code fence
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("llm_picker: JSON 解析失败，raw=%s", raw[:200])
        return {}

    picks_raw = data.get("picks")
    if not isinstance(picks_raw, dict):
        logger.warning("llm_picker: picks 不是 dict，raw=%s", raw[:200])
        return {}

    result: dict[str, str | None] = {}
    for hint, key in picks_raw.items():
        if isinstance(key, str) and key in pool_keys:
            result[hint] = key
        elif key is None or (isinstance(key, str) and key.lower() == "null"):
            result[hint] = None
        else:
            result[hint] = None
    return result


def llm_pick_photos(
    hints: list[str],
    pool_keys: list[str],
    manifest: dict,
    *,
    client: Anthropic,
    model: str,
    location_hint: list[str] | None = None,
) -> dict[str, str | None]:
    """主入口：调 Anthropic API，返回 hint→photo_key 映射。

    hints: 所有 segment 的 visual_hint（如 ["雪落站台 / 寒风劲吹", ...]）
    pool_keys: 候选 photo key 列表（推荐传全部 real photos，让 LLM 自己判断地域优先）
    manifest: _load_manifest() 返回值
    client: Anthropic client 实例（复用项目已有）
    model: 模型名（推荐 haiku，够用且便宜）
    location_hint: 文章地域标签（如 ["poland"]），作为软信号注入 prompt

    失败（网络/解析/空响应）返回 {} → caller 走 keyword fallback。
    """
    if not hints or not pool_keys:
        return {}

    prompt = build_pick_prompt(hints, pool_keys, manifest, location_hint)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_PICK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:
        logger.warning("llm_picker: API 调用失败", exc_info=True)
        return {}

    text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    raw = "".join(text_parts)
    if not raw.strip():
        logger.warning("llm_picker: 空响应")
        return {}

    return parse_pick_response(raw, set(pool_keys))
