"""WeChat 爬虫解析层单测。

用一份离线保存的真实 WeChat 文章 HTML 作为 fixture，
对 `parse_article_html` 和它的辅助函数做白盒测试。

不发起任何网络请求。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.crawler.wechat import (
    _clean_text,
    _decode_biz,
    _fmt_time,
    parse_article_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "wechat_article.html"
EXPECTED_URL = "https://mp.weixin.qq.com/s/e_I-h_tcQnwWs0gT0tvW7Q"


# === fixture 加载 ===

@pytest.fixture(scope="module")
def article_html() -> str:
    assert FIXTURE.exists(), f"fixture 不存在：{FIXTURE}"
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def parsed(article_html: str) -> dict:
    return parse_article_html(article_html, EXPECTED_URL)


# === 顶层字段 ===

@pytest.mark.unit
def test_parse_extracts_title(parsed: dict) -> None:
    assert parsed["title"] == "巴拿马一夜"


@pytest.mark.unit
def test_parse_extracts_author(parsed: dict) -> None:
    assert parsed["author"] == "一方"


@pytest.mark.unit
def test_parse_extracts_account(parsed: dict) -> None:
    assert parsed["account"] == "援翰写心"


@pytest.mark.unit
def test_parse_formats_publish_time(parsed: dict) -> None:
    # 1778500800 → 2026-05-11 20:00 (北京时间)
    assert parsed["publish_time"] == "2026-05-11 20:00"


@pytest.mark.unit
def test_parse_keeps_raw_biz(parsed: dict) -> None:
    assert parsed["biz"] == "MjM5MzI5NTA0Nw=="


@pytest.mark.unit
def test_parse_decodes_biz_id(parsed: dict) -> None:
    assert parsed["biz_id"] == "2393295047"
    assert parsed["biz_id"].isdigit()


@pytest.mark.unit
def test_parse_echoes_url(parsed: dict) -> None:
    assert parsed["url"] == EXPECTED_URL


# === 正文 ===

@pytest.mark.unit
def test_parse_body_strips_html(parsed: dict) -> None:
    body = parsed["body"]
    # 没有残留的标签
    assert "<" not in body and ">" not in body
    # 关键正文片段必须出现
    assert "巴拿马" in body
    assert "玛丽贝尔·莫罗乔" in body
    assert "2026年3月26日晚9:50" in body


@pytest.mark.unit
def test_parse_body_decodes_entities(parsed: dict) -> None:
    body = parsed["body"]
    # &middot; / &bull; / &nbsp; 都应被还原
    assert "·" in body  # middot / bull
    # 不应再出现原始实体
    assert "&nbsp;" not in body
    assert "&middot;" not in body
    assert "&ldquo;" not in body
    assert "&rdquo;" not in body


@pytest.mark.unit
def test_parse_body_keeps_chinese_punctuation(parsed: dict) -> None:
    body = parsed["body"]
    # 中文标点应原样保留
    assert "。" in body
    assert "，" in body
    assert "：" in body


# === 健壮性：缺字段时不要崩 ===

@pytest.mark.unit
def test_parse_returns_empty_strings_on_empty_html() -> None:
    result = parse_article_html("", "")
    assert result["title"] == ""
    assert result["author"] == ""
    assert result["account"] == ""
    assert result["publish_time"] == ""
    assert result["biz"] == ""
    assert result["biz_id"] == ""
    assert result["body"] == ""
    assert result["url"] == ""


@pytest.mark.unit
def test_parse_handles_garbage_html() -> None:
    result = parse_article_html("<html>random noise without markers</html>", "x")
    assert result["title"] == ""
    assert result["publish_time"] == ""
    assert result["body"] == ""


# === 辅助函数 ===

class TestDecodeBiz:
    @pytest.mark.unit
    def test_正常_base64(self) -> None:
        assert _decode_biz("MjM5MzI5NTA0Nw==") == "2393295047"

    @pytest.mark.unit
    def test_空串(self) -> None:
        assert _decode_biz("") == ""

    @pytest.mark.unit
    def test_非法输入不抛异常(self) -> None:
        # 非法 base64 应该原样返回，而不是让上层崩
        assert _decode_biz("@@@not-base64@@@") == "@@@not-base64@@@"


class TestFmtTime:
    @pytest.mark.unit
    def test_正常时间戳(self) -> None:
        # 1778500800 → 2026-05-11 20:00 (CST)
        assert _fmt_time("1778500800") == "2026-05-11 20:00"

    @pytest.mark.unit
    def test_空串(self) -> None:
        assert _fmt_time("") == ""

    @pytest.mark.unit
    def test_非数字(self) -> None:
        assert _fmt_time("not-a-number") == ""

    @pytest.mark.unit
    def test_零(self) -> None:
        # 0 = 1970-01-01 08:00 (CST) - 应正常返回
        result = _fmt_time("0")
        assert "1970" in result


class TestCleanText:
    @pytest.mark.unit
    def test_剥离标签(self) -> None:
        # 标签被替换为换行（而不是空格），所以内联标签之间会有换行
        result = _clean_text("<p>hello <b>world</b></p>")
        assert "<" not in result
        assert ">" not in result
        assert "hello" in result
        assert "world" in result

    @pytest.mark.unit
    def test_合并连续空白(self) -> None:
        # 多个换行应被合并为单个换行
        result = _clean_text("a\n\n\nb")
        assert "\n\n" not in result
        assert "a" in result and "b" in result

    @pytest.mark.unit
    def test_替换_html_实体(self) -> None:
        result = _clean_text("&nbsp;a&nbsp;b&middot;c&mdash;d&ldquo;e&rdquo;f&bull;g")
        assert " " in result  # &nbsp; -> space
        assert "·" in result  # middot + bull
        assert "—" in result  # mdash
        assert '"' in result  # ldquo + rdquo

    @pytest.mark.unit
    def test_空输入(self) -> None:
        assert _clean_text("") == ""

    @pytest.mark.unit
    def test_纯文本原样返回(self) -> None:
        assert _clean_text("hello world") == "hello world"
