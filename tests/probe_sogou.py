"""抓一次搜狗真实搜索结果，dump 原始 HTML 让我们对齐结构。

用法:
    python -m tests.probe_sogou
"""
from __future__ import annotations

import re
from pathlib import Path

from scrapling import Fetcher

OUT = Path("data/probe")


def dump(name: str, content: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(content, encoding="utf-8")
    return p


def main() -> None:
    # type=2 搜文章；type=1 搜公众号
    for typ, label in [(1, "account"), (2, "article")]:
        url = f"https://weixin.sogou.com/weixin?type={typ}&query=%E6%8F%B4%E7%BF%B0%E5%86%99%E5%BF%83&ie=utf8"
        print(f"\n========== {label}: {url} ==========")
        page = Fetcher.get(
            url,
            impersonate="chrome120",
            timeout=30000,
            headers={
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://weixin.sogou.com/",
            },
        )
        text = page.get_all_text(ignore_tags=("script", "style"))
        print(f"  body len: {len(page.body)}")
        print(f"  text len: {len(text)}")
        print(f"  --- first 600 chars of text ---")
        print(text[:600])
        dump(f"{label}.html", page.body.decode("utf-8", errors="replace"))
        dump(f"{label}.txt", text)
        # 检查是否有验证码
        body_text = page.body.decode("utf-8", errors="replace")
        if "验证码" in text or "请输入验证码" in text or "antispider" in body_text.lower():
            print("  ⚠️  触发验证码！")


if __name__ == "__main__":
    main()
