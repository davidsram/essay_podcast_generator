"""app/video/llm_picker.py 单测：prompt 构建 + response 解析。"""
from __future__ import annotations

import pytest

from app.video.llm_picker import build_pick_prompt, parse_pick_response


_MANIFEST: dict = {
    "warsaw_snow": {"caption_hint": "华沙冬港", "scene": ["snow", "city", "winter"], "location": ["poland"]},
    "tatra_mountain": {"caption_hint": "塔特拉松林", "scene": ["nature", "mountain", "forest"], "location": ["poland"]},
    "warsaw_night": {"caption_hint": "华沙夜街", "scene": ["night", "street", "city"], "location": ["poland"]},
}


class TestBuildPickPrompt:
    @pytest.mark.unit
    def test_包含_所有_hint(self) -> None:
        hints = ["雪落站台", "风雪站台", "晨雾"]
        prompt = build_pick_prompt(hints, ["warsaw_snow", "warsaw_night"], _MANIFEST)
        for h in hints:
            assert h in prompt, f"prompt 应包含 hint '{h}'"

    @pytest.mark.unit
    def test_包含_所有_候选图_元数据(self) -> None:
        prompt = build_pick_prompt(["雪"], ["warsaw_snow", "tatra_mountain"], _MANIFEST)
        assert "warsaw_snow" in prompt
        assert "tatra_mountain" in prompt
        assert "华沙冬港" in prompt
        assert "塔特拉松林" in prompt

    @pytest.mark.unit
    def test_无_hint_不_抛(self) -> None:
        prompt = build_pick_prompt([], ["warsaw_snow"], _MANIFEST)
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_无_pool_不_抛(self) -> None:
        prompt = build_pick_prompt(["雪"], [], _MANIFEST)
        assert isinstance(prompt, str)

    @pytest.mark.unit
    def test_pool_key_不在_manifest_中_显示_空_tag(self) -> None:
        prompt = build_pick_prompt(["雾"], ["missing_key"], {})
        assert "missing_key" in prompt


class TestParsePickResponse:
    @pytest.mark.unit
    def test_正常_JSON(self) -> None:
        raw = '{"picks": {"雪": "warsaw_snow", "风": "warsaw_night"}}'
        result = parse_pick_response(raw, {"warsaw_snow", "warsaw_night"})
        assert result == {"雪": "warsaw_snow", "风": "warsaw_night"}

    @pytest.mark.unit
    def test_含_null(self) -> None:
        raw = '{"picks": {"雪": "warsaw_snow", "风": null}}'
        result = parse_pick_response(raw, {"warsaw_snow"})
        assert result == {"雪": "warsaw_snow", "风": None}

    @pytest.mark.unit
    def test_code_fence_剥除(self) -> None:
        raw = '```json\n{"picks": {"雪": "warsaw_snow"}}\n```'
        result = parse_pick_response(raw, {"warsaw_snow"})
        assert result == {"雪": "warsaw_snow"}

    @pytest.mark.unit
    def test_格式_错误_返回_空_dict(self) -> None:
        result = parse_pick_response("not json", {"warsaw_snow"})
        assert result == {}

    @pytest.mark.unit
    def test_空_串_返回_空_dict(self) -> None:
        result = parse_pick_response("", {"warsaw_snow"})
        assert result == {}

    @pytest.mark.unit
    def test_key_不在_pool_中_视为_null(self) -> None:
        raw = '{"picks": {"雪": "fake_key"}}'
        result = parse_pick_response(raw, {"warsaw_snow"})
        assert result == {"雪": None}

    @pytest.mark.unit
    def test_混合_有效_和_无效_key(self) -> None:
        raw = '{"picks": {"雪": "warsaw_snow", "风": "bad_key", "雾": null}}'
        result = parse_pick_response(raw, {"warsaw_snow"})
        assert result == {"雪": "warsaw_snow", "风": None, "雾": None}

    @pytest.mark.unit
    def test_picks_不是_dict_返回_空(self) -> None:
        raw = '{"picks": ["not a dict"]}'
        result = parse_pick_response(raw, {"warsaw_snow"})
        assert result == {}
