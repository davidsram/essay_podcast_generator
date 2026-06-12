"""抓单篇文章，dump 正文 + __biz。

用法:
    python -m tests.probe_article
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from scrapling import Fetcher

URL = "https://mp.weixin.qq.com/s/e_I-h_tcQnwWs0gT0tvW7Q"
OUT = Path("data/probe")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = Fetcher.get(
        URL,
        impersonate="chrome120",
        timeout=30000,
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://mp.weixin.qq.com/",
        },
    )
    html = p.body.decode("utf-8", errors="replace")
    print(f"status: {p.status_code if hasattr(p, 'status_code') else '?'}")
    print(f"body len: {len(html)}")
    (OUT / "article.html").write_text(html, encoding="utf-8")

    # __biz
    biz = re.search(r"__biz=([A-Za-z0-9%+/=_-]+)", html)
    print(f"__biz: {biz.group(1) if biz else '(not found)'}")

    # 公众号名
    name = re.search(r'<a[^>]+id="js_name"[^>]*>([^<]+)</a>', html)
    print(f"公众号名: {name.group(1).strip() if name else '(?)'}")

    # 标题
    title = re.search(r'<h2[^>]+class="rich_media_title[^"]*"[^>]*>(.*?)</h2>', html, re.DOTALL)
    print(f"标题: {title.group(1).strip() if title else '(?)'}")

    # 作者
    author = re.search(r'<span[^>]+class="rich_media_meta rich_media_meta_text"[^>]*>([^<]+)</span>', html)
    author = re.sub(r"<[^>]+>", "", author.group(1)).strip() if author else ""
    if not author:
        author = re.search(r'var\s+author\s*=\s*["\']([^"\']+)["\']', html)
        author = author.group(1).strip() if author else ""
    print(f"作者: {author or '(?)'}")

    # 时间
    t = re.search(r'var\s+publish_time\s*=\s*["\']([^"\']+)["\']', html)
    print(f"publish_time: {t.group(1) if t else '(?)'}")

    # 检查是否触发反爬
    if "环境异常" in html or "访问频繁" in html or "verify" in html.lower() and "captcha" in html.lower():
        print("⚠️  触发反爬！")

    # 抓 #js_content
    body_match = re.search(
        r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL
    )
    if body_match:
        body_html = body_match.group(1)
        (OUT / "body.html").write_text(body_html, encoding="utf-8")
        # 去标签
        text = re.sub(r"<[^>]+>", "\n", body_html)
        text = re.sub(r"\n+", "\n", text).strip()
        (OUT / "body.txt").write_text(text, encoding="utf-8")
        print(f"正文长度: {len(text)}")
        print("--- 前 800 字 ---")
        print(text[:800])
    else:
        print("⚠️  没找到 #js_content")


if __name__ == "__main__":
    main()
