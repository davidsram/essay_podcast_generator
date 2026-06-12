"""app/video/pexels_client.py 单测：缓存/下载/失败路径。"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.video.pexels_client import PexelsClient


class TestPexelsClient:
    @pytest.fixture
    def client(self, tmp_path: Path) -> PexelsClient:
        return PexelsClient("fake_key_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", tmp_path / "cache")

    @pytest.mark.unit
    def test_空_api_key_抛_ValueError(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="非空"):
            PexelsClient("", tmp_path / "cache")

    @pytest.mark.unit
    def test_query_hash_稳定_且_12字符(self) -> None:
        h1 = PexelsClient.query_hash("snow night")
        h2 = PexelsClient.query_hash("snow night")
        h3 = PexelsClient.query_hash("rain day")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 12

    @pytest.mark.unit
    def test_缓存目录_自动创建(self, tmp_path: Path) -> None:
        cache = tmp_path / "sub" / "dir"
        c = PexelsClient("k", cache)
        assert cache.exists()

    @pytest.mark.unit
    def test_索引_损坏_重置_不抛(self, client: PexelsClient) -> None:
        client._index_path.write_text("not json{", encoding="utf-8")
        client._load_index()
        assert client._index == {}

    @pytest.mark.unit
    def test_get_or_download_缓存命中_不调网络(self, client: PexelsClient) -> None:
        # 预置缓存：写一个空 jpg 占位 + 索引
        qhash = PexelsClient.query_hash("snow night")
        fname = f"pexels_999_{qhash}.jpg"
        (client.cache_dir / fname).write_bytes(b"\xff\xd8\xff\xd9")  # 最小 jpg
        client._index[qhash] = fname
        client._save_index()
        with patch.object(client, "search") as mock_search:
            result = client.get_or_download("snow night")
        mock_search.assert_not_called()
        assert result is not None
        path, meta = result
        assert path.name == fname
        assert meta.get("cache_hit") is True

    @pytest.mark.unit
    def test_get_or_download_缓存指_文件_不在_重搜(
        self, client: PexelsClient
    ) -> None:
        # 索引指向不存在的文件 → 应清掉索引然后重搜
        qhash = PexelsClient.query_hash("snow night")
        client._index[qhash] = "missing.jpg"
        with patch.object(client, "search", return_value=[]):
            result = client.get_or_download("snow night")
        assert result is None
        assert qhash not in client._index

    @pytest.mark.unit
    def test_get_or_download_第一次_失败_试_fallback(
        self, client: PexelsClient
    ) -> None:
        # search 第一次返空，第二次返真实数据
        photo = {
            "id": 12345, "src": {"large": "http://example.com/photo.jpg"},
            "photographer": "X", "alt": "snow",
        }
        with patch.object(client, "search", side_effect=[[], [photo]]), \
             patch.object(client, "_download", return_value=client.cache_dir / "ok.jpg"):
            result = client.get_or_download("primary", fallback_queries=["fallback1"])
        assert result is not None
        path, meta = result
        assert meta.get("id") == 12345

    @pytest.mark.unit
    def test_get_or_download_全失败_返_None(self, client: PexelsClient) -> None:
        with patch.object(client, "search", side_effect=Exception("network")):
            result = client.get_or_download("snow", fallback_queries=["rain", "fog"])
        assert result is None

    @pytest.mark.unit
    def test_search_调用_urllib_并_带_Authorization(
        self, client: PexelsClient
    ) -> None:
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps({"photos": [{"id": 1}]}).encode()
            mock_urlopen.return_value = mock_resp
            photos = client.search("snow", per_page=2)
        assert photos == [{"id": 1}]
        # 验证 Authorization header 设置了
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.headers.get("Authorization") == client.api_key
        assert "query=snow" in req.full_url
        assert "per_page=2" in req.full_url
        assert "orientation=portrait" in req.full_url


class TestTokenizeFallback:
    """_tokenize_fallback：LLM 失败时的中英翻译兜底。"""

    def test_拉丁词_原样_返回(self) -> None:
        from app.video.photo_searcher import _tokenize_fallback
        # 中英混排 → 抽第一个拉丁 token（lowercase）
        assert _tokenize_fallback("在 Warsaw 见到雪") == "warsaw"

    def test_纯中文_tokenize(self) -> None:
        from app.video.photo_searcher import _tokenize_fallback
        result = _tokenize_fallback("雪夜车站")
        # 应包含 snow/night/station 至少 1 个
        assert any(w in result for w in ("snow", "night", "station"))

    def test_实在_不行_用_hint_原串(self) -> None:
        from app.video.photo_searcher import _tokenize_fallback
        result = _tokenize_fallback("张三李四")
        # 中文人名不在字典里 → 返回原串
        assert result == "张三李四"
