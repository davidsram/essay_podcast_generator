"""微信公众号爬虫（HTTP only，依赖 scrapling 的 Fetcher）。

能拿到的：
1) 单篇文章 URL → 标题 / 作者 / 发布时间 / 正文 / __biz
2) 搜狗 type=2 → 关键词相关的文章列表（注意：不是公众号自己的文章）

不能做到的（没装 Chromium）：
- 公众号主页 (mp/homepage) 的历史文章分页列表（需要 JS 动态渲染）
"""
from __future__ import annotations

import base64
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass

from scrapling import Fetcher


@dataclass
class Article:
    title: str
    url: str
    author: str
    summary: str
    cover: str
    publish_time: str  # ISO 格式


# === 单篇文章解析 ===

_BIZ_RE = re.compile(r"""var\s+biz\s*=\s*['"]([^'"]+)['"]""")
_TITLE_RE = re.compile(r'<span class="js_title_inner">([^<]+)</span>')
_AUTHOR_RE = re.compile(r'<span[^>]+id="js_author_name"[^>]*>([^<]+)</span>')
_ACCT_RE = re.compile(r'<a[^>]+id="js_name"[^>]*>([^<]+)</a>')
_TIME_RE = re.compile(r"var\s+create_time\s*=\s*['\"](\d+)['\"]")
_PUB_TIME_RE = re.compile(r"var\s+publish_time\s*=\s*['\"](\d+)['\"]")
_BODY_RE = re.compile(
    r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*<script',
    re.DOTALL,
)


def _decode_biz(biz: str) -> str:
    """__biz 字段是 base64 编码的公众号数字 ID。"""
    try:
        return base64.b64decode(biz).decode()
    except Exception:
        return biz


def _fmt_time(ts: str) -> str:
    if not ts or not ts.isdigit():
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", "\n", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&ldquo;", '"')
        .replace("&rdquo;", '"')
        .replace("&mdash;", "—")
        .replace("&middot;", "·")
        .replace("&bull;", "·")
    )
    text = re.sub(r"\n+", "\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_article_html(html: str, url: str = "") -> dict:
    """从 WeChat 文章 HTML 中提取字段。纯字符串处理，便于测试。

    返回 {title, author, account, publish_time, biz, biz_id, body, url}。
    """
    title_m = _TITLE_RE.search(html)
    author_m = _AUTHOR_RE.search(html)
    acct_m = _ACCT_RE.search(html)
    biz_m = _BIZ_RE.search(html)
    time_m = _TIME_RE.search(html)
    pub_m = _PUB_TIME_RE.search(html)
    body_m = _BODY_RE.search(html)

    body = _clean_text(body_m.group(1)) if body_m else ""

    return {
        "title": title_m.group(1).strip() if title_m else "",
        "author": author_m.group(1).strip() if author_m else "",
        "account": acct_m.group(1).strip() if acct_m else "",
        "publish_time": _fmt_time((time_m or pub_m).group(1)) if (time_m or pub_m) else "",
        "biz": biz_m.group(1) if biz_m else "",
        "biz_id": _decode_biz(biz_m.group(1)) if biz_m else "",
        "body": body,
        "url": url,
    }


def fetch_article(url: str) -> dict:
    """抓单篇文章。返回 {title, author, account, publish_time, biz, body, url}。

    url 必须是 mp.weixin.qq.com/s/... 形式（搜狗中转链要先跳过去再调一次）。
    自动清洗：反转义 `&amp;`、剥 `#wechat_redirect`、强制 https。
    """
    from app.crawler.wcplus import clean_wechat_url
    url = clean_wechat_url(url)
    p = Fetcher.get(
        url,
        impersonate="chrome120",
        timeout=30000,
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://mp.weixin.qq.com/",
        },
    )
    html = p.body.decode("utf-8", errors="replace")
    return parse_article_html(html, url)


# === 搜狗 type=2 文章搜索 ===

def _build_search_url(keyword: str, page: int = 1) -> str:
    params = {"type": "2", "query": keyword, "ie": "utf8", "page": str(page)}
    return "https://weixin.sogou.com/weixin?" + urllib.parse.urlencode(params)


_LI_BLOCK_RE = re.compile(
    r'<li id="sogou_vr_11002601_box_\d+"[^>]*>(.*?)</li>', re.DOTALL
)
_TITLE_IN_BLOCK_RE = re.compile(
    r'uigs="article_title_\d+"[^>]*>(.*?)</a>', re.DOTALL
)
_HREF_IN_BLOCK_RE = re.compile(
    r'<a data-z="art"[^>]+href="([^"]+)"', re.DOTALL
)
_SUMMARY_IN_BLOCK_RE = re.compile(
    r'class="txt-info"[^>]*>(.*?)</p>', re.DOTALL
)
_ACCOUNT_IN_BLOCK_RE = re.compile(
    r'<span class="all-time-y2">([^<]+)</span>'
)
_TS_IN_BLOCK_RE = re.compile(r"timeConvert\('(\d+)'\)")


def search_articles(keyword: str, limit: int = 10, page: int = 1) -> list[Article]:
    """通过搜狗微信搜文章。注意：返回的是关键词相关文章，不一定是某个公众号原创。"""
    p = Fetcher.get(
        _build_search_url(keyword, page=page),
        impersonate="chrome120",
        timeout=30000,
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://weixin.sogou.com/",
        },
    )
    html = p.body.decode("utf-8", errors="replace")

    if "暂无与" in html and "相关的微信公众号文章" in html:
        return []

    results: list[Article] = []
    for blk in _LI_BLOCK_RE.findall(html):
        t = _TITLE_IN_BLOCK_RE.search(blk)
        if not t:
            continue
        title = re.sub(r"<[^>]+>", "", t.group(1)).strip()

        u = _HREF_IN_BLOCK_RE.search(blk)
        href = ("https://weixin.sogou.com" + u.group(1)) if u else ""

        s = _SUMMARY_IN_BLOCK_RE.search(blk)
        summary = re.sub(r"<[^>]+>", "", s.group(1)).strip()[:200] if s else ""

        a = _ACCOUNT_IN_BLOCK_RE.search(blk)
        account = a.group(1).strip() if a else ""

        ts = _TS_IN_BLOCK_RE.search(blk)
        ts_int = int(ts.group(1)) if ts else 0
        publish = _fmt_time(str(ts_int)) if ts_int else ""

        results.append(
            Article(
                title=title,
                url=href,
                author=account,
                summary=summary,
                cover="",
                publish_time=publish,
            )
        )
        if len(results) >= limit:
            break
    return results
