"""真文章 demo：从缓存挑一篇 → LLM 摘要成脚本 → compose 渲染。

用法:
    python -m tests.real_demo [article_id]

不传 article_id 默认用 '难忘的波兰华尔兹'（2966 字，雪/火车/波兰视觉强）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.config import settings
from app.llm.base import get_backend
from app.video.article_context import extract_article_context
from app.video.composer import _REAL_PHOTO_KEYS, _load_manifest, compose_script
from app.video.llm_picker import llm_pick_photos
from app.video.pexels_client import PexelsClient
from app.video.photo_searcher import PhotoSearcher


# 候选：标题 → 文件 stem
DEFAULT_ARTICLE_STEM = "05ed6aadd2673dd8110fe9bb9a7a0342"  # 难忘的波兰华尔兹
DEFAULT_ARTICLE_TITLE = "难忘的波兰华尔兹"


def _clean_body(raw: str) -> str:
    """剥掉头部那堆'阅读全文/扫一扫'噪音。"""
    cleaned = re.sub(
        r"^(阅读全文|\s|预览时标签不可点|微信扫一扫|关注该公众号|"
        r"继续滑动看下一个|轻触阅读原文|援翰写心|)+",
        "", raw,
    )
    return cleaned.strip()


def main() -> None:
    stem = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ARTICLE_STEM
    cache_path = settings.data_dir / "cache" / f"{stem}.json"
    if not cache_path.exists():
        print(f"[real_demo] 缓存不存在: {cache_path}")
        print("[real_demo] 可用的 stem:")
        for p in sorted((settings.data_dir / "cache").glob("*.json"))[:10]:
            print(f"  {p.stem[:32]}")
        sys.exit(1)

    article = json.loads(cache_path.read_text())
    title = article.get("title", DEFAULT_ARTICLE_TITLE)
    author = article.get("author", "援翰写心")
    body = _clean_body(article.get("body", ""))
    print(f"[real_demo] 文章: {title} ({len(body)} 字)")
    print(f"[real_demo] 发布: {article.get('publish_time', '?')}")

    # 1) LLM 摘要 → VideoScript
    print("[real_demo] 调用 LLM 摘要...")
    backend = get_backend("claude")
    script = backend.summarize_to_script(
        title=title, author=author, body=body, target_seconds=75,
    )
    print(f"[real_demo] LLM 输出: {len(script.segments)} 段, closing='{script.closing}'")
    for i, seg in enumerate(script.segments):
        print(f"  [{i}] {seg.visual_hint:<12} | {seg.text[:50]}…")

    # 2) 文章级地域 context 提取（中英关键词字典，不调 LLM）
    article_ctx = extract_article_context(title, body)
    print(f"[real_demo] article_context: location_tags={article_ctx['location_tags']}")

    # 2.5) LLM 语义选图：一次调用为全部 visual_hint 映射最匹配的照片
    # 候选池给 LLM 传全部 real 图 + 地域作为软信号，让 LLM 自主判断"该文章该不该用地域图"
    manifest = _load_manifest()
    bg_dir = settings.asset_bg_dir
    hints = [seg.visual_hint for seg in script.segments]
    seg_texts = [seg.text for seg in script.segments]
    pool_keys = [p.stem for p in bg_dir.glob("*.png") if p.stem in _REAL_PHOTO_KEYS]
    loc_tags = (article_ctx or {}).get("location_tags", [])
    print(f"[real_demo] LLM 选图: {len(hints)} hints × {len(pool_keys)} candidates"
          + (f" (loc={loc_tags})" if loc_tags else ""))
    llm_picks = llm_pick_photos(
        hints, pool_keys, manifest,
        client=backend.client, model="claude-haiku-4-5-20251001",
        location_hint=loc_tags or None,
    )
    for hint, key in llm_picks.items():
        print(f"  [{hint}] → {key or '(keyword fallback)'}")

    # 2.6) Pexels 搜图（替换 LLM 选图；失败软降级）
    photo_paths: dict = {}
    if settings.pexels_api_key:
        pexels = PexelsClient(
            settings.pexels_api_key,
            settings.data_dir / "photo_cache",
        )
        searcher = PhotoSearcher(
            pexels, client=backend.client, model="claude-haiku-4-5-20251001",
        )
        photo_paths = searcher.fetch_all(hints, texts=seg_texts)
        for hint, result in photo_paths.items():
            if result:
                path, meta = result
                print(f"  [pexels] {hint} → {path.name}  by {meta.get('photographer')}")
            else:
                print(f"  [pexels] {hint} → (fallback to LLM pick)")
    else:
        print("[real_demo] 未配置 PEXELS_API_KEY，跳过搜图")

    # 3) compose → mp4（传 body 让 BGM 按内容关键词打分挑；article_context 让 polaroid 走地域 cascade）
    work = settings.data_dir / "real_demo"
    out = settings.output_dir / f"real_demo_{stem[:8]}.mp4"
    if out.exists():
        out.unlink()
    print(f"[real_demo] 输出: {out}")
    compose_script(
        script, work, out,
        body=body, article_context=article_ctx,
        llm_picks=llm_picks, photo_paths=photo_paths,
    )
    print(f"[real_demo] OK  size = {out.stat().st_size / 1024:.1f} KB")
    print(f"[real_demo] 打开: open {out}")


if __name__ == "__main__":
    main()
