"""本地缓存层：把 fetch_article 的结果按 wcplusPro 的 article id 存盘。

调用方通常不知道 id（直接传 URL 来），所以接口是 `fetch_article_cached(url, wcplus_id=None)`：
- 给 id 且命中缓存 → 直接返回缓存（不再走网络）
- 没给 id / 没命中 → 走 `fetch_article`，可选地把结果写盘

文件格式就是 `fetch_article` 那个 dict 的 JSON 直出：
    {title, author, account, publish_time, biz, biz_id, body, url}

放在 `data/cache/{wcplus_id}.json`。加 `cache_meta` 字段记一些溯源信息
（什么时间从哪个 URL 拿的）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.crawler.wechat import fetch_article

CACHE_DIR: Path = Path(__file__).resolve().parent.parent.parent / "data" / "cache"


def cache_path(article_id: str) -> Path:
    return CACHE_DIR / f"{article_id}.json"


def is_cached(article_id: str) -> bool:
    return cache_path(article_id).exists()


def load_cached(article_id: str) -> dict | None:
    """读缓存；不存在 / 损坏返回 None。"""
    p = cache_path(article_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cached(
    article_id: str,
    article: dict,
    *,
    source_url: str | None = None,
) -> Path:
    """写缓存。带 `cache_meta` 字段记录溯源。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = dict(article)
    out["cache_meta"] = {
        "fetched_at": time.time(),
        "wcplus_id": article_id,
        "source_url": source_url or article.get("url", ""),
    }
    p = cache_path(article_id)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def fetch_article_cached(url: str, wcplus_id: str | None = None) -> dict:
    """优先读缓存，没命中才走网络。"""
    if wcplus_id:
        cached = load_cached(wcplus_id)
        if cached is not None:
            return cached
    article = fetch_article(url)
    # 只有 body 非空才值得缓存
    if wcplus_id and article.get("body"):
        save_cached(wcplus_id, article, source_url=url)
    return article


def list_cached() -> list[dict[str, Any]]:
    """列出所有已缓存文章（按 wcplus_id 排）。"""
    if not CACHE_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(CACHE_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": p.stem,
                    "title": d.get("title", ""),
                    "author": d.get("author", ""),
                    "publish_time": d.get("publish_time", ""),
                    "body_len": len(d.get("body", "")),
                }
            )
        except (json.JSONDecodeError, OSError):
            continue
    return out
