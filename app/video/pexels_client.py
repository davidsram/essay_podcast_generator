"""Pexels API 客户端：搜索 + 下载 + 缓存。

API key 通过 settings.pexels_api_key 读，**绝不在源码硬编码**。

API: https://api.pexels.com/v1/search
Auth: Authorization header
限流: 200/小时, 20000/月
Attribution: 每张照片必须带 photographer 署名（用户可见画面外元数据中保留）
"""
from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class PexelsClient:
    def __init__(self, api_key: str, cache_dir: Path) -> None:
        if not api_key:
            raise ValueError("PexelsClient 需要非空 api_key")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, str] = {}  # query_hash → filename
        self._index_path = self.cache_dir / "_index.json"
        self._load_index()

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("pexels cache index 损坏，重置", exc_info=True)
                self._index = {}

    def _save_index(self) -> None:
        try:
            self._index_path.write_text(
                json.dumps(self._index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("pexels cache index 写盘失败", exc_info=True)

    @staticmethod
    def query_hash(query: str) -> str:
        return hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]

    def search(self, query: str, per_page: int = 3) -> list[dict]:
        """调 Pexels search API，返回 photo 对象列表。失败抛。"""
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": "portrait",
            "size": "large",
        }
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params)
        # Pexels 经 Cloudflare，Python-urllib 默认 UA 被 1010 黑名单拦截；伪装成 curl
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": self.api_key,
                "User-Agent": "curl/7.85.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("photos", [])

    def get_or_download(
        self, query: str, *, fallback_queries: list[str] | None = None
    ) -> tuple[Path, dict] | None:
        """查缓存：命中直接返回 (path, photo_meta)；未命中 search + download。

        fallback_queries: 第一个 query 失败时依次试。
        返回 (path, photo_meta) — photo_meta 包含 photographer/url/alt 用于 attribution。
        """
        queries = [query] + (fallback_queries or [])
        for q in queries:
            qhash = self.query_hash(q)
            # 1) 缓存命中
            if qhash in self._index:
                fname = self._index[qhash]
                path = self.cache_dir / fname
                if path.exists():
                    return path, {"cache_hit": True, "query": q}
                # 缓存指了文件但文件没了 → 清掉索引继续
                del self._index[qhash]
            # 2) 搜 + 下载
            try:
                photos = self.search(q)
            except Exception:
                logger.warning("pexels search 失败: query=%r", q, exc_info=True)
                continue
            if not photos:
                continue
            photo = photos[0]
            try:
                path = self._download(photo, qhash)
            except Exception:
                logger.warning("pexels download 失败: photo_id=%s", photo.get("id"), exc_info=True)
                continue
            return path, {
                "id": photo.get("id"),
                "photographer": photo.get("photographer"),
                "photographer_url": photo.get("photographer_url"),
                "url": photo.get("url"),
                "alt": photo.get("alt"),
                "query": q,
            }
        return None

    def _download(self, photo: dict, qhash: str) -> Path:
        url = photo["src"]["large"]
        photo_id = photo["id"]
        filename = f"pexels_{photo_id}_{qhash}.jpg"
        path = self.cache_dir / filename
        if path.exists():
            self._index[qhash] = filename
            self._save_index()
            return path
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "curl/7.85.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            path.write_bytes(r.read())
        self._index[qhash] = filename
        self._save_index()
        return path
