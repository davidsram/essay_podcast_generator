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

# 首要原则：内容匹配（最重要）
- 搜索词必须紧扣这段正文的**实际场景**：地点（具体国家/城市/场所）+ 主体 + 动作 + 时间/天气/光照
- 比如正文是"雨夜巴马科机场候机"，搜索词应该是 "africa airport terminal night" / "mali airport runway" / "passenger waiting boarding gate"——不要写成"misty mountains" / "rainy street" 这种泛化意象
- 严禁把"雨/夜/风/雪/远山"等高频古风词当主词，那样 Pexels 会返回江南水乡/日本老街等与正文无关的图
- 视觉提示词（visual_hint）如果是泛化古风意象（"远山烟雨"/"墨竹轻摇"），以**正文**为准，忽略那个 hint

# 次要：风格倾向
- 优选 abstract / minimalist / texture / silhouette / negative-space /
  ink-wash / monochrome / quiet scenes 等基调词（但前提是已经锚定了正确场景）
- 避开人像特写、logo、文字水印、繁复构图，以及能清晰辨认具体人物、
  建筑或品牌物体的照片——这些会被 _apply_bg_treatment 模糊+降饱和+米色蒙版处理
- 强构图、留白、单色调比细节丰富的照片更适合后期处理

# 命名技巧
- 用具体名词（避免 "beautiful" / "stunning" 等抽象形容词）
- 多角度：候选词可换拍摄角度、镜头距离、风格
- 加地点修饰：场景名词前带国家/城市/大洲（如 "moroccan market"、"kyoto alley"）能大幅提升相关性

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


_RERANK_SYSTEM_PROMPT = """你是一个视频配图质检员。我会给你几段视频的提示词+正文，以及每段对应的候选照片。
请为每段选出最匹配的照片序号（1-5），或返回 null（都不合适）。

# 核心规则：内容匹配 > 风格匹配
- 候选照片只看 alt 描述和摄影师名，判断是否与**正文实际场景**匹配
- 明显不匹配的（如正文是"非洲机场候机"但照片是"日本老街雨巷" / 正文是"草原落日"但照片是"江南水乡"）→ 必须返回 null
- 地域/年代/活动不吻合（如正文讲 21 世纪非洲，候选是 19 世纪日本）→ null
- 风格（misty/abstract/sepia）不能作为匹配依据——风格对但内容错也不算匹配

# 软规则
- 人物活动不对（如正文是"机场等行李"但照片是"婚礼准备"）→ null
- 主体不对（如正文是"母亲"但照片是"父亲"或"陌生人"）→ null
- 有合适的就选最贴的，不要勉强——宁可 null 走 fallback，不要错配

返回格式（严格 JSON）：
{"picks": {"提示词1": 3, "提示词2": null, ...}}"""


def _rerank_photos(
    hints: list[str],
    texts: list[str],
    candidates: dict[str, list[dict]],
    *,
    client: Anthropic,
    model: str,
) -> dict[str, int | None]:
    """LLM 对每段的候选照片 rerank，返回 hint→best_index (1-based) 或 None。"""
    if not hints:
        return {}

    lines: list[str] = []
    for i, hint in enumerate(hints):
        lines.append(f"\n## {hint}")
        if i < len(texts) and texts[i].strip():
            lines.append(f"  正文：{texts[i].strip()[:150]}")
        photos = candidates.get(hint, [])
        if not photos:
            lines.append("  (无候选)")
            continue
        for j, p in enumerate(photos):
            alt = p.get("alt", "") or ""
            photographer = p.get("photographer", "") or ""
            avg = p.get("avg_color", "") or ""
            lines.append(f"  {j+1}. [{alt}]  by {photographer}  color={avg}")
    body = "\n".join(lines)

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_RERANK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"候选照片：\n{body}\n\n请为每段选出最匹配的序号或 null。返回 JSON。"}],
        )
    except Exception:
        logger.warning("rerank: LLM 调用失败", exc_info=True)
        return {}

    text_parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
    raw = "".join(text_parts).strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("rerank: JSON 解析失败 raw=%s", raw[:200])
        return {}

    picks = data.get("picks", {})
    if not isinstance(picks, dict):
        return {}

    result: dict[str, int | None] = {}
    for hint, idx in picks.items():
        if isinstance(idx, int) and 1 <= idx <= 5:
            result[hint] = idx
        else:
            result[hint] = None
    return result


class PhotoSearcher:
    """编排：LLM expand + Pexels 搜索 + LLM rerank + 下载，返回 hint→(Path, meta) 映射。"""

    def __init__(self, pexels: PexelsClient, *, client: Anthropic, model: str) -> None:
        self.pexels = pexels
        self.client = client
        self.model = model

    def fetch_all(
        self, hints: list[str], *, texts: list[str] | None = None,
    ) -> dict[str, tuple[Path, dict] | None]:
        """LLM 扩词 → Pexels 搜 5 张 → LLM rerank 挑最优 → 下载。

        texts 可选：每段口播正文，传给 expand_hints + rerank 让 LLM 理解完整语境。
        """
        if not hints:
            return {}

        texts = texts or [""] * len(hints)

        # 1) LLM 扩词
        queries = expand_hints(
            hints, texts=texts, client=self.client, model=self.model,
        )

        # 2) Pexels 搜多张（只拿元数据）
        candidates: dict[str, list[dict]] = {}
        for hint in hints:
            terms = queries.get(hint) or [_tokenize_fallback(hint)]
            photos: list[dict] = []
            for t in terms[:2]:  # 只搜前 2 个词，每个 5 张
                batch = self.pexels.search_multi(t, per_page=5)
                photos.extend(batch)
                if len(photos) >= 5:
                    break
            # 去重（按 id）
            seen_ids = set()
            unique: list[dict] = []
            for p in photos:
                pid = p.get("id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    unique.append(p)
            candidates[hint] = unique[:5]

        # 3) LLM rerank：挑最优
        best_indices = _rerank_photos(
            hints, texts, candidates, client=self.client, model=self.model,
        )

        # 4) 下载选中的
        result: dict[str, tuple[Path, dict] | None] = {}
        for hint in hints:
            idx = best_indices.get(hint)
            photos = candidates.get(hint, [])
            if idx is not None and 1 <= idx <= len(photos):
                photo = photos[idx - 1]
                try:
                    qhash = self.pexels.query_hash(photo.get("alt", "") or str(photo["id"]))
                    path = self.pexels._download(photo, qhash)
                    result[hint] = (path, {
                        "id": photo.get("id"),
                        "photographer": photo.get("photographer"),
                        "photographer_url": photo.get("photographer_url"),
                        "url": photo.get("url"),
                        "alt": photo.get("alt"),
                        "reranked": True,
                    })
                except Exception:
                    logger.warning("PhotoSearcher: download 失败 hint=%r", hint, exc_info=True)
                    result[hint] = None
            else:
                result[hint] = None
        return result
