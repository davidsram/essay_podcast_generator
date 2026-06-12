"""app/crawler/cache.py 单测。

用 tmp_path 隔离 CACHE_DIR，monkeypatch 替换掉 `fetch_article` 避免真联网。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.crawler import cache as cache_mod
from app.crawler.cache import (
    cache_path,
    fetch_article_cached,
    is_cached,
    list_cached,
    load_cached,
    save_cached,
)


# === 工具 fixture ===

@pytest.fixture
def fake_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 cache_mod.CACHE_DIR 指向 tmp_path。"""
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """替换掉 cache_mod.fetch_article，记调用。"""
    m = MagicMock()
    monkeypatch.setattr(cache_mod, "fetch_article", m)
    return m


def _article(id_: str = "id1", body: str = "正文一段") -> dict[str, Any]:
    return {
        "title": "标题",
        "author": "作者",
        "account": "公众号",
        "publish_time": "2026-01-01",
        "biz": "BIZ",
        "biz_id": id_,
        "body": body,
        "url": "https://mp.weixin.qq.com/s?x=1",
    }


# === 路径 / 元数据 ===

class TestCachePath:
    @pytest.mark.unit
    def test_路径在_cache_dir_下(self, fake_cache_dir: Path) -> None:
        p = cache_path("abc123")
        assert p.parent == fake_cache_dir
        assert p.name == "abc123.json"

    @pytest.mark.unit
    def test_id_含特殊字符_仍_可_作_文件名(self, fake_cache_dir: Path) -> None:
        # wcplusPro 的 id 是 md5-ish，可以直接作文件名
        p = cache_path("ced5d4f2c32d1672f3d83b26c9c8fbae")
        assert p.name == "ced5d4f2c32d1672f3d83b26c9c8fbae.json"


class TestIsCached:
    @pytest.mark.unit
    def test_没文件_False(self, fake_cache_dir: Path) -> None:
        assert is_cached("nope") is False

    @pytest.mark.unit
    def test_有文件_True(self, fake_cache_dir: Path) -> None:
        (fake_cache_dir / "yes.json").write_text("{}", encoding="utf-8")
        assert is_cached("yes") is True


# === load_cached ===

class TestLoadCached:
    @pytest.mark.unit
    def test_不存在_返回_None(self, fake_cache_dir: Path) -> None:
        assert load_cached("missing") is None

    @pytest.mark.unit
    def test_正常_返回_dict(self, fake_cache_dir: Path) -> None:
        payload = {"title": "t", "body": "b"}
        (fake_cache_dir / "a.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        assert load_cached("a") == payload

    @pytest.mark.unit
    def test_坏_JSON_返回_None_不_抛(self, fake_cache_dir: Path) -> None:
        (fake_cache_dir / "bad.json").write_text("not json{", encoding="utf-8")
        assert load_cached("bad") is None


# === save_cached ===

class TestSaveCached:
    @pytest.mark.unit
    def test_写盘_带_cache_meta(self, fake_cache_dir: Path) -> None:
        art = _article("id1", body="正文")
        p = save_cached("id1", art, source_url="https://x.com/s?a=1")
        assert p == fake_cache_dir / "id1.json"
        assert p.exists()
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["title"] == "标题"
        assert d["body"] == "正文"
        # cache_meta 三件套
        meta = d["cache_meta"]
        assert meta["wcplus_id"] == "id1"
        assert meta["source_url"] == "https://x.com/s?a=1"
        assert isinstance(meta["fetched_at"], (int, float))
        assert meta["fetched_at"] > 0

    @pytest.mark.unit
    def test_不传_source_url_回退_到_article_url(self, fake_cache_dir: Path) -> None:
        art = _article("id1")
        save_cached("id1", art)
        d = json.loads((fake_cache_dir / "id1.json").read_text(encoding="utf-8"))
        assert d["cache_meta"]["source_url"] == art["url"]

    @pytest.mark.unit
    def test_不_改_原_article_对象(self, fake_cache_dir: Path) -> None:
        art = _article("id1")
        save_cached("id1", art)
        # 原对象没多出 cache_meta 字段（避免脏写原 dict）
        assert "cache_meta" not in art

    @pytest.mark.unit
    def test_覆盖_旧_缓存(self, fake_cache_dir: Path) -> None:
        save_cached("id1", _article("id1", body="旧"))
        save_cached("id1", _article("id1", body="新"))
        d = load_cached("id1")
        assert d["body"] == "新"


# === fetch_article_cached（核心） ===

class TestFetchArticleCached:
    @pytest.mark.unit
    def test_有_id_且_命中_不_走_fetch(
        self, fake_cache_dir: Path, fake_fetch: MagicMock
    ) -> None:
        save_cached("id1", _article("id1", body="cached"))
        out = fetch_article_cached("https://x.com/s?x=1", wcplus_id="id1")
        assert out["body"] == "cached"
        fake_fetch.assert_not_called()

    @pytest.mark.unit
    def test_有_id_但_未_命中_走_fetch_且_写缓存(
        self, fake_cache_dir: Path, fake_fetch: MagicMock
    ) -> None:
        fake_fetch.return_value = _article("id1", body="new body")
        out = fetch_article_cached("https://x.com/s?x=1", wcplus_id="id1")
        assert out["body"] == "new body"
        fake_fetch.assert_called_once_with("https://x.com/s?x=1")
        # 写盘成功
        assert is_cached("id1")
        on_disk = load_cached("id1")
        assert on_disk["body"] == "new body"
        assert on_disk["cache_meta"]["source_url"] == "https://x.com/s?x=1"

    @pytest.mark.unit
    def test_有_id_body_空_不_写盘_但_仍_返回(
        self, fake_cache_dir: Path, fake_fetch: MagicMock
    ) -> None:
        fake_fetch.return_value = _article("id1", body="")
        out = fetch_article_cached("https://x.com/s?x=1", wcplus_id="id1")
        assert out["body"] == ""
        # 不写盘
        assert not is_cached("id1")

    @pytest.mark.unit
    def test_没_id_也_走_fetch_但_不_写盘(
        self, fake_cache_dir: Path, fake_fetch: MagicMock
    ) -> None:
        fake_fetch.return_value = _article("id1", body="b")
        out = fetch_article_cached("https://x.com/s?x=1")
        assert out["body"] == "b"
        fake_fetch.assert_called_once()
        # 缓存目录里没文件
        assert list(fake_cache_dir.glob("*.json")) == []

    @pytest.mark.unit
    def test_fetch_抛错_原样抛_不_写盘(
        self, fake_cache_dir: Path, fake_fetch: MagicMock
    ) -> None:
        fake_fetch.side_effect = RuntimeError("网络炸了")
        with pytest.raises(RuntimeError, match="网络炸了"):
            fetch_article_cached("https://x.com/s?x=1", wcplus_id="id1")
        assert not is_cached("id1")


# === list_cached ===

class TestListCached:
    @pytest.mark.unit
    def test_目录不存在_空列表(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path / "nope")
        assert list_cached() == []

    @pytest.mark.unit
    def test_列_出_每篇_摘要(self, fake_cache_dir: Path) -> None:
        save_cached("a", _article("a", body="12345"))
        save_cached("b", _article("b", body="67890"))
        out = list_cached()
        assert len(out) == 2
        # 按 id 排序
        assert out[0]["id"] == "a"
        assert out[1]["id"] == "b"
        assert out[0]["body_len"] == 5
        assert out[0]["title"] == "标题"
        assert out[0]["author"] == "作者"
        assert out[0]["publish_time"] == "2026-01-01"

    @pytest.mark.unit
    def test_坏_JSON_跳过_不_抛(self, fake_cache_dir: Path) -> None:
        save_cached("good", _article("good"))
        (fake_cache_dir / "bad.json").write_text("not json", encoding="utf-8")
        out = list_cached()
        assert len(out) == 1
        assert out[0]["id"] == "good"
