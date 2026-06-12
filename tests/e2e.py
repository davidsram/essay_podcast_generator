"""端到端测试：从数据库取一篇文章 → mock LLM → 合成视频。

用法:
    python -m tests.e2e                  # 跑最新一条
    python -m tests.e2e --row 1          # 跑指定行
    python -m tests.e2e --url <url>      # 跑指定 URL
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from app.config import settings
from app.llm.base import get_backend
from app.video.composer import compose_script

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "articles.db"


def load_article_from_db(url: str | None = None) -> dict:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    if url:
        row = con.execute("SELECT * FROM articles WHERE url=?", (url,)).fetchone()
    else:
        row = con.execute(
            "SELECT * FROM articles ORDER BY publish_time DESC LIMIT 1"
        ).fetchone()
    con.close()
    if not row:
        raise RuntimeError("数据库为空，请先 python -m tests.ingest <urls>")
    return dict(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="数据库里的 URL，不传则取最新一条")
    ap.add_argument("--backend", default="mock", help="LLM 后端: mock / claude / minimax")
    args = ap.parse_args()

    article = load_article_from_db(args.url)
    print(f"[e2e] 标题: {article['title']}")
    print(f"[e2e] 作者: {article['author']}")
    print(f"[e2e] 公众号: {article.get('account', '')}")
    print(f"[e2e] 时间: {article['publish_time']}")
    print(f"[e2e] 正文字数: {len(article['body'])}")

    backend = get_backend(args.backend)
    print(f"[e2e] LLM 后端: {backend.name}")
    script = backend.summarize_to_script(
        title=article["title"],
        author=article["author"],
        body=article["body"],
        target_seconds=settings.video_duration,
    )
    print(f"[e2e] 脚本生成: 标题={script.title!r}, {len(script.segments)} 段")
    for i, seg in enumerate(script.segments, 1):
        print(f"   段{i}: {seg.text[:60]}…")

    # 合成
    job_id = f"e2e_{int(time.time())}"
    work = settings.data_dir / job_id
    out = settings.output_dir / f"{job_id}.mp4"
    print(f"[e2e] 合成: {out}")
    compose_script(script, work, out)
    print(f"[e2e] OK  {out.stat().st_size / 1024:.1f} KB")
    print(f"[e2e] 打开: open {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
