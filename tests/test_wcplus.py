"""wcplusPro 客户端单测。用 requests-mock 模拟 5001，不真连本机。"""
from __future__ import annotations

import pytest
import requests_mock

from app.crawler.wcplus import (
    WcplusClient,
    WcplusError,
    clean_wechat_url,
)


# === clean_wechat_url ===

class TestCleanWechatUrl:
    @pytest.mark.unit
    def test_反转义_amp(self) -> None:
        assert (
            clean_wechat_url("https://mp.weixin.qq.com/s?a=1&amp;b=2")
            == "https://mp.weixin.qq.com/s?a=1&b=2"
        )

    @pytest.mark.unit
    def test_剥_锚点(self) -> None:
        assert clean_wechat_url("https://x.com/s?a=1#wechat_redirect") == "https://x.com/s?a=1"

    @pytest.mark.unit
    def test_http_升_https(self) -> None:
        assert clean_wechat_url("http://mp.weixin.qq.com/s?x=1").startswith("https://")

    @pytest.mark.unit
    def test_三件_一起(self) -> None:
        raw = "http://mp.weixin.qq.com/s?a=1&amp;b=2#wechat_redirect"
        out = clean_wechat_url(raw)
        assert out == "https://mp.weixin.qq.com/s?a=1&b=2"

    @pytest.mark.unit
    def test_空(self) -> None:
        assert clean_wechat_url("") == ""

    @pytest.mark.unit
    def test_已经是_https_不动(self) -> None:
        assert clean_wechat_url("https://mp.weixin.qq.com/s?x=1") == "https://mp.weixin.qq.com/s?x=1"


# === WcplusClient ===

BASE = "http://localhost:5001"


def _mock_gzh_list(m: requests_mock.Mocker, gzhs: list[dict] | None = None) -> None:
    m.get(f"{BASE}/api/gzh/list", json={"Gzhs": gzhs or []})


def _mock_articles(m: requests_mock.Mocker, biz: str, articles: list[dict] | None = None) -> None:
    m.get(
        f"{BASE}/api/report/gzh_articles",
        json={"Articles": articles or [], "Gzh": {"Biz": biz, "Nickname": "援翰写心"}},
    )


@pytest.fixture
def rm() -> requests_mock.Mocker:
    with requests_mock.Mocker() as m:
        yield m


class TestListAccounts:
    @pytest.mark.unit
    def test_返回_WcplusAccount_列表(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(
            rm,
            [
                {
                    "Biz": "MjM5MzI5NTA0Nw==",
                    "Nickname": "援翰写心",
                    "Status": "finished",
                    "TotalArticleNum": 74,
                },
                {
                    "Biz": "MzA3NjE2NDAyOQ==",
                    "Nickname": "马来西亚旅游局",
                    "Status": "finished",
                    "TotalArticleNum": 100,
                },
            ],
        )
        accs = WcplusClient().list_accounts()
        assert len(accs) == 2
        assert accs[0].nickname == "援翰写心"
        assert accs[0].total_articles == 74
        assert accs[0].status == "finished"

    @pytest.mark.unit
    def test_空_列表(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(rm, [])
        assert WcplusClient().list_accounts() == []


class TestFindAccount:
    @pytest.mark.unit
    def test_找到_finished_的(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(
            rm,
            [{"Biz": "BIZ", "Nickname": "援翰写心", "Status": "finished", "TotalArticleNum": 74}],
        )
        acc = WcplusClient().find_account("援翰写心")
        assert acc.biz == "BIZ"
        assert acc.status == "finished"

    @pytest.mark.unit
    def test_找不到_抛错(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(rm, [])
        with pytest.raises(WcplusError, match="找不到公众号"):
            WcplusClient().find_account("不存在")

    @pytest.mark.unit
    def test_状态非_finished_抛错(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(
            rm,
            [{"Biz": "BIZ", "Nickname": "援翰写心", "Status": "running", "TotalArticleNum": 10}],
        )
        with pytest.raises(WcplusError, match="未完成采集"):
            WcplusClient().find_account("援翰写心")


class TestListArticles:
    @pytest.mark.unit
    def test_正常_返回文章_含字段映射(self, rm: requests_mock.Mocker) -> None:
        _mock_articles(
            rm,
            "BIZ",
            [
                {
                    "ID": "abc123",
                    "Title": "巴拿马一夜",
                    "Author": "一方",
                    "PDate": 1778500800,
                    "ContentURL": "https://mp.weixin.qq.com/s?a=1&amp;b=2#wechat_redirect",
                    "Digest": "援翰写心/巴拿马一夜",
                    "Cover": "https://mmbiz.qpic.cn/x.jpg",
                    "ReadNum": 138,
                    "LikeNum": 10,
                    "ShareNum": 6,
                }
            ],
        )
        arts = WcplusClient().list_articles("BIZ", limit=5)
        assert len(arts) == 1
        a = arts[0]
        assert a.id == "abc123"
        assert a.title == "巴拿马一夜"
        assert a.author == "一方"
        assert a.publish_time == 1778500800
        # URL 已清洗
        assert a.url == "https://mp.weixin.qq.com/s?a=1&b=2"
        assert "#" not in a.url
        assert "&amp;" not in a.url
        # 互动数据
        assert a.read_num == 138
        assert a.like_num == 10
        assert a.share_num == 6
        # digest / cover
        assert a.digest == "援翰写心/巴拿马一夜"
        assert a.cover == "https://mmbiz.qpic.cn/x.jpg"

    @pytest.mark.unit
    def test_空_返回空列表(self, rm: requests_mock.Mocker) -> None:
        _mock_articles(rm, "BIZ", [])
        assert WcplusClient().list_articles("BIZ", limit=10) == []

    @pytest.mark.unit
    def test_limit_0_不发请求(self, rm: requests_mock.Mocker) -> None:
        # 不注册 mock：若发了请求会抛 NoMockAddress
        assert WcplusClient().list_articles("BIZ", limit=0) == []

    @pytest.mark.unit
    def test_缺字段_用默认值(self, rm: requests_mock.Mocker) -> None:
        _mock_articles(
            rm,
            "BIZ",
            [{"ID": "x", "Title": "t", "Biz": "BIZ", "PDate": 100, "ContentURL": ""}],
        )
        a = WcplusClient().list_articles("BIZ")[0]
        assert a.author == ""
        assert a.url == ""
        assert a.read_num == 0
        assert a.like_num == 0
        assert a.digest == ""


class TestErrorHandling:
    @pytest.mark.unit
    def test_连不上_报清晰错(self, rm: requests_mock.Mocker) -> None:
        # 完全不注册任何 mock，requests-mock 抛 NoMockAddress，真机会抛 ConnectionError。
        # 两条路径都该被 WcplusError 接住并给出可读中文消息。
        with pytest.raises(WcplusError, match="wcplusPro"):
            WcplusClient().list_accounts()

    @pytest.mark.unit
    def test_超时_报清晰错(self, rm: requests_mock.Mocker) -> None:
        import requests as _req
        rm.get(f"{BASE}/api/gzh/list", exc=_req.exceptions.Timeout)
        with pytest.raises(WcplusError, match="调用超时"):
            WcplusClient(timeout=0.1).list_accounts()

    @pytest.mark.unit
    def test_非_200_报清晰错(self, rm: requests_mock.Mocker) -> None:
        rm.get(f"{BASE}/api/gzh/list", status_code=500, text="oops")
        with pytest.raises(WcplusError, match="返回 HTTP 500"):
            WcplusClient().list_accounts()

    @pytest.mark.unit
    def test_非_JSON_报清晰错(self, rm: requests_mock.Mocker) -> None:
        rm.get(f"{BASE}/api/gzh/list", text="<html>oops</html>")
        with pytest.raises(WcplusError, match="返回非 JSON"):
            WcplusClient().list_accounts()


class TestToDict:
    @pytest.mark.unit
    def test_account_to_dict(self, rm: requests_mock.Mocker) -> None:
        _mock_gzh_list(rm, [{"Biz": "B", "Nickname": "n", "Status": "finished", "TotalArticleNum": 1}])
        d = WcplusClient().list_accounts()[0].to_dict()
        assert d == {"biz": "B", "nickname": "n", "total_articles": 1, "status": "finished"}
