"""入库脚本：抓一批文章存到 SQLite + 输出摘要。

用法:
    python -m tests.ingest urls.txt
    python -m tests.ingest --search "援翰写心" --limit 5
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from app.crawler.wechat import fetch_article, search_articles

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "articles.db"


def init_db() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            url TEXT PRIMARY KEY,
            title TEXT,
            author TEXT,
            account TEXT,
            publish_time TEXT,
            biz TEXT,
            biz_id TEXT,
            body TEXT,
            body_len INTEGER,
            fetched_at TEXT
        );
    """)
    con.commit()
    con.close()


def upsert_article(d: dict) -> None:
    con = sqlite3.connect(DB)
    con.execute(
        """
        INSERT INTO articles(url, title, author, account, publish_time, biz, biz_id, body, body_len, fetched_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
            title=excluded.title,
            author=excluded.author,
            account=excluded.account,
            publish_time=excluded.publish_time,
            biz=excluded.biz,
            biz_id=excluded.biz_id,
            body=excluded.body,
            body_len=excluded.body_len,
            fetched_at=excluded.fetched_at
        """,
        (
            d["url"],
            d["title"],
            d["author"],
            d.get("account", ""),
            d["publish_time"],
            d.get("biz", ""),
            d.get("biz_id", ""),
            d["body"],
            len(d["body"]),
            time.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    con.commit()
    con.close()


def list_articles() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT url, title, author, account, publish_time, body_len FROM articles ORDER BY publish_time DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls_file", nargs="?", help="每行一个 mp.weixin.qq.com/s/... URL")
    ap.add_argument("--search", help="用搜狗搜索关键词")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--list", action="store_true", help="只列已入库的")
    args = ap.parse_args()

    init_db()

    if args.list:
        for r in list_articles():
            print(f"  {r['publish_time']:16s}  {r['author']:12s}  {r['title'][:50]}  ({r['body_len']}字)")
        return 0

    urls: list[str] = []
    if args.urls_file:
        urls = [
            u.strip()
            for u in Path(args.urls_file).read_text().splitlines()
            if u.strip() and "mp.weixin.qq.com" in u
        ]
    if args.search:
        arts = search_articles(args.search, limit=args.limit)
        print(f"[搜狗] 关键词「{args.search}」命中 {len(arts)} 条：")
        for a in arts:
            print(f"  {a.publish_time}  [{a.author}]  {a.title[:50]}")
        # 不自动入库，只列出（避免污染）
        return 0
    if not urls:
        print("需要 urls_file 或 --search")
        return 1

    print(f"[抓取] {len(urls)} 条 URL")
    for i, u in enumerate(urls, 1):
        try:
            d = fetch_article(u)
            upsert_article(d)
            print(f"  [{i:02d}/{len(urls)}] {d['publish_time']:16s}  {d['author']:8s}  {d['title'][:40]}  ({len(d['body'])}字)  biz={d['biz']}")
        except Exception as e:  # noqa: BLE001
            print(f"  [{i:02d}/{len(urls)}] 失败：{e}")
        time.sleep(1)  # 礼貌性 delay

    print(f"\n[入库完成] {DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
