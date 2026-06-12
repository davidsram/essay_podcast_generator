"""文章级地域/主题 context 提取（不调 LLM，纯正则 + 中英关键词字典）。

援翰写心的文章常混排 CJK + 拉丁文（"Bradley 在 Warsaw 见到了波兰朋友"），
所以关键词字典必须中英双轨。

返回 dict 结构（与 _pick_background 的 article_context kwarg 对齐）：
    {
      "location_tags": ["poland", "usa"],  # 按命中次数降序
    }

tags 用英文 enum-style（不是中文），便于 manifest.json 里 location 字段直接匹配，
也便于未来扩展到 era/theme（同样的英文 tag 体系）。
"""
from __future__ import annotations

# 中英双轨关键词字典。每个 tag 对应一组关键词，只要任一命中即记一次。
_ARTICLE_LOCATION_KEYWORDS: dict[str, list[str]] = {
    "poland":  ["波兰", "华沙", "克拉科夫", "波兰人", "波兰语",
                "Poland", "Warsaw", "Krakow", "Polish"],
    "russia":  ["俄国", "俄罗斯", "苏联", "莫斯科", "苏联人",
                "Russia", "Soviet", "Moscow"],
    "japan":   ["日本", "东京", "京都", "大阪", "霓虹", "樱花",
                "Japan", "Tokyo", "Kyoto", "Osaka"],
    "france":  ["法国", "巴黎", "塞纳", "普罗旺斯",
                "France", "Paris", "Seine", "Provence"],
    "uk":      ["英国", "伦敦", "英伦",
                "England", "London", "Britain"],
    "italy":   ["意大利", "罗马", "佛罗伦萨", "威尼斯",
                "Italy", "Rome", "Florence", "Venice"],
    "germany": ["德国", "柏林", "慕尼黑",
                "Germany", "Berlin", "Munich"],
    "china":   ["中国", "江南", "徽州", "苏州", "杭州", "北京", "上海",
                "China", "Jiangnan"],
    "usa":     ["美国", "纽约", "华盛顿", "威斯康星",
                "America", "New York", "Washington", "Wisconsin"],
}


def extract_article_context(title: str, body: str) -> dict[str, list[str]]:
    """从标题 + 正文前 4k 字 regex 出地域 tag。

    优先级：标题 > 正文。
    - 标题里的地域词是"文章主题"的强信号（「难忘的波兰华尔兹」→波兰），
      命中即用标题（无视正文其他地域）。
    - 正文里的"中国饭 / 日本料理 / 苏联时期的对比"等常是借代 / 食物 / 回忆，
      不是 setting。必须用阈值过滤——只保留 ≥ max(3, top_count × 0.4) 的 tag，
      排除 1-2 次偶发提及。

    Args:
        title: 文章标题（独立搜一次，因为标题常含明确地域）
        body:  正文（截前 4000 字）

    Returns:
        {"location_tags": [...]}  按命中次数降序，最多 ~3 项
    """
    # 1) 标题优先：标题里有地域词即信标题
    title_hits = _count_hits(title)
    if title_hits:
        sorted_tags = sorted(title_hits.items(), key=lambda x: -x[1])
        return {"location_tags": [t for t, _ in sorted_tags]}

    # 2) 正文兜底：用阈值过滤（排除偶发提及）
    body_hits = _count_hits(body[:4000])
    if not body_hits:
        return {"location_tags": []}

    sorted_tags = sorted(body_hits.items(), key=lambda x: -x[1])
    top_count = sorted_tags[0][1]
    # 阈值：top 的过半（ceil），至少 2。
    #   - 至少 2 避免"中国饭 ×1"这种偶发提及混入 setting
    #   - 过半保证 ≥top×50% 的强地域都进；弱地域（≤top×40%）被过滤
    #   - 例：top=3 → threshold=2；tags with [3,2,1,1] → [poland, russia]
    threshold = max(2, (top_count + 1) // 2)
    primary = [t for t, c in sorted_tags if c >= threshold]
    return {"location_tags": primary}


def _count_hits(text: str) -> dict[str, int]:
    """数每个 tag 的关键词命中次数（去重——同一 keyword 多次出现只算一次）。"""
    hits: dict[str, int] = {}
    for tag, kws in _ARTICLE_LOCATION_KEYWORDS.items():
        n = sum(1 for kw in kws if kw in text)
        if n > 0:
            hits[tag] = n
    return hits