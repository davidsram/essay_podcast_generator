"""app/video/photo_searcher.py 单测：LLM expand + 编排。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.video.photo_searcher import PhotoSearcher, expand_hints
from app.video import photo_searcher as ps_mod


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

    def test_系统_prompt_内容_匹配_优先_于_风格(self) -> None:
        """Pexels 搜索词必须紧扣正文场景，风格偏好降为次要。

        历史教训：用户反馈"图片内容是江南鱼乡，与正文不符"——
        因为旧 prompt 把 abstract/minimalist/水墨 等风格词放到首位，
        LLM 倾向返回水墨/水乡/雨巷类图，与文章实际场景（机场/草原/老照片）无关。

        新 prompt：内容匹配是首要原则，风格偏好降为次要。
        """
        prompt = ps_mod._EXPAND_SYSTEM_PROMPT
        # 首要原则：内容匹配 / 场景锚定
        primary = ["内容匹配", "实际场景", "地点", "正文"]
        for kw in primary:
            assert kw in prompt, f"系统 prompt 缺内容匹配关键词 {kw!r}"
        # 仍保留风格倾向作为软偏好
        secondary = ["abstract", "minimalist"]
        for kw in secondary:
            assert kw in prompt.lower(), f"系统 prompt 应保留风格词 {kw!r} 作为次要参考"
        # 不再把 abstract 当作首要原则——确认没有"风格倾向（重要）"的旧表述
        assert "风格倾向（重要）" not in prompt, "旧表述『风格倾向（重要）』已废弃，应改为次要"

    def test_rerank_prompt_内容_优先_且_地域_不_符_必须_null(self) -> None:
        """rerank prompt 必须把内容匹配放首位，且明确要求地域/年代/活动不符 → null。

        历史教训：旧 prompt 只说"明显不匹配就 null"，但 Pexels alt 描述模糊，
        江南鱼乡 vs 非洲机场在 LLM 看来都是"雨中夜景"，就被误选。
        新 prompt：风格不能当匹配依据，地域/年代/活动不符硬性 null。
        """
        prompt = ps_mod._RERANK_SYSTEM_PROMPT
        assert "内容匹配 > 风格匹配" in prompt, "rerank 应把内容匹配放首位"
        assert "不能作为匹配依据" in prompt or "不能当匹配依据" in prompt, (
            "rerank 应明确风格不是匹配依据"
        )
        # 关键硬规则：地域不吻合必须 null
        assert "地域" in prompt and "null" in prompt, (
            "rerank 应包含『地域不吻合 → null』的硬规则"
        )


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
