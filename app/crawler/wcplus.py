"""wcplusPro 客户端（本地 5001 端口）。

封装三类只读接口：
  1) /api/gzh/list        列出已导入的公众号
  2) /api/report/gzh_articles  按 Biz 列出文章
  3) /api/article/content 取单篇元数据（注意：wcplusPro 不存正文，正文走我们自己的 fetch_article）

对外只暴露「公众号视图」和「文章视图」，把 wcplusPro 的字段名
（Biz / Nickname / PDate / ContentURL / ReadNum / LikeNum ...）映射成项目自己的 dataclass。

不发起任何 wcplusPro 之外的网络请求。
"""
from __future__ import annotations

import html
from dataclasses import asdict, dataclass

import requests


DEFAULT_BASE_URL = "http://localhost:5001"


class WcplusError(RuntimeError):
    """wcplusPro 不可用或调用失败。"""


@dataclass(frozen=True)
class WcplusAccount:
    biz: str
    nickname: str
    total_articles: int
    status: str  # finished / running / ...

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WcplusArticle:
    id: str
    title: str
    author: str
    publish_time: int  # Unix 时间戳（秒）
    url: str           # mp.weixin.qq.com/s/... （自动 https + 去锚点 + 反转义 &amp;）
    digest: str
    cover: str
    read_num: int
    like_num: int
    share_num: int

    def to_dict(self) -> dict:
        return asdict(self)


# === URL 清洗 ===
# wcplusPro 给的 ContentURL 长这样：
#   http://mp.weixin.qq.com/s?__biz=...&amp;mid=...&amp;...#wechat_redirect
# 三件事必须处理：
#   1) &amp; → & （HTML 实体反转义）
#   2) #wechat_redirect （剥掉，否则某些客户端会拒）
#   3) http:// → https:// （http 在微信域会被 501）
def clean_wechat_url(raw: str) -> str:
    if not raw:
        return ""
    return html.unescape(raw).split("#", 1)[0].replace("http://", "https://", 1)


# === 客户端 ===

class WcplusClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, **params: int | str) -> dict:
        try:
            r = requests.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            raise WcplusError(f"wcplusPro 调用超时（{self.timeout}s）") from e
        except Exception as e:
            # 真机：ConnectionError / SSLError / DNS 失败...
            # 测试：requests-mock 的 NoMockAddress（不是 requests 子类）
            # 一律包成「连不上」的友好消息
            raise WcplusError(
                f"连不上 wcplusPro（{self.base_url}），请确认它已启动"
            ) from e
        if r.status_code != 200:
            raise WcplusError(f"wcplusPro {path} 返回 HTTP {r.status_code}：{r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise WcplusError(f"wcplusPro {path} 返回非 JSON：{r.text[:200]}") from e

    # --- 公众号 ---

    def list_accounts(self) -> list[WcplusAccount]:
        """列出所有已导入的公众号。"""
        d = self._get(
            "/api/gzh/list",
            offset=0,
            num=200,
            sort="updated_at",
            direction="desc",
        )
        return [
            WcplusAccount(
                biz=g["Biz"],
                nickname=g["Nickname"],
                total_articles=int(g.get("TotalArticleNum", 0)),
                status=g.get("Status", ""),
            )
            for g in d.get("Gzhs", [])
        ]

    def find_account(self, nickname: str) -> WcplusAccount:
        """按昵称查一个公众号；要求 status=finished。"""
        for a in self.list_accounts():
            if a.nickname == nickname:
                if a.status != "finished":
                    raise WcplusError(
                        f"公众号「{nickname}」状态={a.status}，未完成采集，无法取文章"
                    )
                return a
        raise WcplusError(f"wcplusPro 中找不到公众号「{nickname}」，请先在客户端里导入")

    # --- 文章 ---

    def list_articles(self, biz: str, limit: int = 10) -> list[WcplusArticle]:
        """按 Biz 列最近 limit 篇（按发布时间倒序）。"""
        if limit <= 0:
            return []
        d = self._get(
            "/api/report/gzh_articles",
            biz=biz,
            offset=0,
            num=limit,
            sort="p_date",
            direction="desc",
        )
        out: list[WcplusArticle] = []
        for a in d.get("Articles", []):
            out.append(
                WcplusArticle(
                    id=a["ID"],
                    title=a["Title"],
                    author=a.get("Author", ""),
                    publish_time=int(a.get("PDate", 0)),
                    url=clean_wechat_url(a.get("ContentURL", "")),
                    digest=a.get("Digest", ""),
                    cover=a.get("Cover", ""),
                    read_num=int(a.get("ReadNum", 0)),
                    like_num=int(a.get("LikeNum", 0)),
                    share_num=int(a.get("ShareNum", 0)),
                )
            )
        return out
