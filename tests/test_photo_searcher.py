"""app/video/photo_searcher.py 单测：LLM expand + 编排。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.video.photo_searcher import PhotoSearcher, expand_hints


def _make_msg(text: str) -> MagicMock:
    """构造一个 mock 的 Anthropic messages response。"""
    msg = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg.content = [block]
    return msg


class TestExpandHints:
    @pytest.mark.unit
    def test_空_hints_返_空_dict(self) -> None:
        result = expand_hints([], client=MagicMock(), model="m")
        assert result == {}

    @pytest.mark.unit
    def test_正常_JSON_解析(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '{"queries": {"雪": ["snow night", "winter station"], "风": ["wind"]}}'
        )
        result = expand_hints(["雪", "风"], client=client, model="haiku")
        assert result == {"雪": ["snow night", "winter station"], "风": ["wind"]}

    @pytest.mark.unit
    def test_code_fence_剥除(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '```json\n{"queries": {"雪": ["snow"]}}\n```'
        )
        result = expand_hints(["雪"], client=client, model="haiku")
        assert result == {"雪": ["snow"]}

    @pytest.mark.unit
    def test_string_包_单条_queries_归_一_为_list(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '{"queries": {"雪": "snow night"}}'
        )
        result = expand_hints(["雪"], client=client, model="haiku")
        assert result == {"雪": ["snow night"]}

    @pytest.mark.unit
    def test_空_queries_补_tokenize_fallback(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '{"queries": {"雪": [], "烛": ["candle"]}}'
        )
        result = expand_hints(["雪", "烛"], client=client, model="haiku")
        # 雪 之前是 [] → 应被 tokenize_fallback 补一个
        assert len(result["雪"]) == 1
        assert result["烛"] == ["candle"]

    @pytest.mark.unit
    def test_LLM_调用_失败_返_空(self) -> None:
        client = MagicMock()
        client.messages.create.side_effect = Exception("network")
        result = expand_hints(["雪"], client=client, model="haiku")
        assert result == {}

    @pytest.mark.unit
    def test_格式_错误_JSON_返_空(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg("not json")
        result = expand_hints(["雪"], client=client, model="haiku")
        assert result == {}

    @pytest.mark.unit
    def test_queries_不_是_dict_返_空(self) -> None:
        client = MagicMock()
        client.messages.create.return_value = _make_msg('{"queries": "string"}')
        result = expand_hints(["雪"], client=client, model="haiku")
        assert result == {}


class TestPhotoSearcher:
    @pytest.mark.unit
    def test_空_hints_返_空(self, tmp_path: Path) -> None:
        from app.video.pexels_client import PexelsClient
        pexels = PexelsClient("fake", tmp_path / "cache")
        s = PhotoSearcher(pexels, client=MagicMock(), model="haiku")
        assert s.fetch_all([]) == {}

    @pytest.mark.unit
    def test_LLM_失败_回退_tokenize_且_pexels_成功(
        self, tmp_path: Path
    ) -> None:
        from app.video.pexels_client import PexelsClient
        pexels = PexelsClient("fake", tmp_path / "cache")
        client = MagicMock()
        client.messages.create.side_effect = Exception("LLM down")
        s = PhotoSearcher(pexels, client=client, model="haiku")

        # 预置缓存让 Pexels 命中
        qhash = PexelsClient.query_hash("snow night")
        fname = f"pexels_999_{qhash}.jpg"
        (pexels.cache_dir / fname).write_bytes(b"fake")
        pexels._index[qhash] = fname
        pexels._save_index()

        result = s.fetch_all(["雪夜"])
        # tokenize 命中 "snow night" → 缓存命中
        assert result["雪夜"] is not None
        path, meta = result["雪夜"]
        assert path.name == fname

    @pytest.mark.unit
    def test_Pexels_全_失败_返_None(self, tmp_path: Path) -> None:
        from app.video.pexels_client import PexelsClient
        pexels = PexelsClient("fake", tmp_path / "cache")
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '{"queries": {"雪": ["snow"]}}'
        )
        s = PhotoSearcher(pexels, client=client, model="haiku")
        with patch.object(pexels, "get_or_download", return_value=None):
            result = s.fetch_all(["雪"])
        assert result["雪"] is None

    @pytest.mark.unit
    def test_编排_正常_路径(self, tmp_path: Path) -> None:
        from app.video.pexels_client import PexelsClient
        pexels = PexelsClient("fake", tmp_path / "cache")
        client = MagicMock()
        client.messages.create.return_value = _make_msg(
            '{"queries": {"雪": ["snow night station", "winter station"]}}'
        )
        s = PhotoSearcher(pexels, client=client, model="haiku")
        expected = (pexels.cache_dir / "ok.jpg", {"id": 1, "photographer": "X"})
        with patch.object(pexels, "get_or_download", return_value=expected) as mock:
            result = s.fetch_all(["雪"])
        assert result["雪"] == expected
        # 验证传了 primary + fallback_queries
        call = mock.call_args
        assert call[0][0] == "snow night station"
        assert "winter station" in call[1].get("fallback_queries", [])
