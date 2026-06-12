"""把 wcplusPro 列表中的文章正文全部缓存到本地。

读 wcplusPro 的 SQLite 拿 article id + content_url，
挨篇走 `fetch_article`，把结果存到 `data/cache/{id}.json`。

用法：
    python -m tests.wcplus_cache --nickname 援翰写心
    python -m tests.wcplus_cache --nickname 援翰写心 --limit 3
    python -m tests.wcplus_cache --nickname 援翰写心 --refresh   # 强制重抓已缓存
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from app.crawler.cache import CACHE_DIR, cache_path, save_cached
from app.crawler.wechat import fetch_article
from app.crawler.wcplus import clean_wechat_url

DEFAULT_DB = Path.home() / "Downloads" / "wcplusPro_macos_apple_silicon" / "db_folder" / "test.db"


def _load_articles(db_path: Path, biz: str, limit: int) -> list[sqlite3.Row]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT id, title, content_url, p_date, author "
        "FROM articles WHERE biz=? ORDER BY p_date DESC"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = con.execute(sql, (biz,)).fetchall()
    con.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--nickname", required=True, help="wcplusPro 里的公众号昵称")
    ap.add_argument("--limit", type=int, default=0, help="最多缓存几篇（0 = 全部）")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="wcplusPro 的 SQLite 路径")
    ap.add_argument("--out", default=str(CACHE_DIR), help="缓存目录")
    ap.add_argument("--retry", type=int, default=2, help="每篇重试次数")
    ap.add_argument("--refresh", action="store_true", help="忽略已缓存的条目重新抓")
    ap.add_argument("--sleep", type=float, default=1.5, help="每篇之间的间隔秒（防反爬）")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"❌ 找不到 wcplusPro 数据库：{db_path}")
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    gzh = con.execute("SELECT * FROM gzhs WHERE nickname=?", (args.nickname,)).fetchone()
    if not gzh:
        print(f"❌ wcplusPro 里找不到公众号「{args.nickname}」")
        return 1
    con.close()
    print(f"✓ 公众号「{gzh['nickname']}」({gzh['total_article_num']} 篇)")

    rows = _load_articles(db_path, gzh["biz"], args.limit)
    print(f"待缓存：{len(rows)} 篇")
    print(f"缓存目录：{out_dir}")
    print()

    ok, skipped, failed = 0, 0, []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        aid = row["id"]
        title_short = (row["title"] or "(无标题)")[:30]
        cp = cache_path(aid)
        if cp.exists() and not args.refresh:
            print(f"  [{i:2d}/{len(rows)}] ⏭  {title_short:30s} 已缓存")
            skipped += 1
            continue

        raw_url = row["content_url"]
        url = clean_wechat_url(raw_url)
        print(f"  [{i:2d}/{len(rows)}] ⤓ {title_short:30s} ", end="", flush=True)

        last_err: str | None = None
        for attempt in range(args.retry + 1):
            try:
                article = fetch_article(url)
                if not article.get("body"):
                    raise RuntimeError("正文为空（可能被反爬）")
                save_cached(aid, article, source_url=raw_url)
                body_len = len(article["body"])
                print(f"✓ {body_len} 字")
                ok += 1
                last_err = None
                break
            except Exception as e:  # noqa: BLE001
                last_err = repr(e)
                if attempt < args.retry:
                    wait = (attempt + 1) * 3
                    print(f"retry in {wait}s ({e!r}) ", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f"✗ {e!r}")
        if last_err:
            failed.append((aid, row["title"], last_err))

        if i < len(rows):
            time.sleep(args.sleep)

    dt = time.time() - t0
    print()
    print(f"完成：✓ {ok} 新缓存  ⏭ {skipped} 跳过  ✗ {len(failed)} 失败  用时 {dt:.0f}s")
    if failed:
        print()
        print("失败列表：")
        for aid, title, err in failed:
            print(f"  {aid}  {title}  {err}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
