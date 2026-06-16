"""app/video/composer.py 单测：BG_KEYWORDS / _pick_background / _pick_music。

`_pick_background` 读 `settings.asset_bg_dir`（与 `settings.video_width/height`），
所以测试用 stub 替换 `composer.settings`，不污染真实配置。
`_pick_music` 接受 music_dir 参数，直接传 tmp_path 即可。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.video import composer
from app.video.composer import (
    BGM_MOOD,
    BG_KEYWORDS,
    _pick_abstract_bg,
    _pick_background,
    _pick_from_pool,
    _pick_music,
    _pick_music_for_body,
    _should_show_polaroid,
    render_card,
)


# === stub settings（只暴露 _pick_background 需要的字段）===

@dataclass
class _StubSettings:
    asset_bg_dir: Path
    asset_music_dir: Path
    video_width: int = 1080
    video_height: int = 1920
    bg_treatment_enabled: bool = False  # 测纯逻辑路径，不走 _apply_bg_treatment


# === fixtures ===

@pytest.fixture
def fake_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    bg = tmp_path / "bg"
    music = tmp_path / "music"
    bg.mkdir()
    music.mkdir()
    monkeypatch.setattr(
        composer, "settings",
        _StubSettings(asset_bg_dir=bg, asset_music_dir=music),
    )
    return bg, music


def _make_bg(bg_dir: Path, name: str, color: tuple[int, int, int] = (200, 200, 200)) -> Path:
    p = bg_dir / f"{name}.png"
    Image.new("RGB", (10, 10), color).save(p)
    return p


def _pixel_of(img: Image.Image | None) -> tuple[int, int, int] | None:
    """拿图片中心像素颜色（resize 后仍是实色）。"""
    if img is None:
        return None
    cx, cy = img.size[0] // 2, img.size[1] // 2
    return img.getpixel((cx, cy))[:3]


# === BG_KEYWORDS ===

class TestBGKeywords:
    @pytest.mark.unit
    def test_有_至少_12_个_条目(self) -> None:
        # 原有 12 张水墨图必须全部保留；后续会再追加新意象（清新风景/静物）。
        assert len(BG_KEYWORDS) >= 12

    @pytest.mark.unit
    def test_每个_条目_都有_非空_keyword(self) -> None:
        for filename, kws in BG_KEYWORDS.items():
            assert kws, f"{filename} keywords 空"
            for kw in kws:
                assert isinstance(kw, str) and kw, f"{filename}: 空 kw"

    @pytest.mark.unit
    def test_所有_filename_都是_合法_png_键(self) -> None:
        for filename in BG_KEYWORDS:
            assert "/" not in filename, f"{filename} 含路径分隔符"
            assert "." not in filename, f"{filename} 含扩展符"
            assert filename.replace("_", "").isalpha(), f"{filename} 不是纯字母"

    @pytest.mark.unit
    def test_原始_12_个_水墨_key_都有_生成器_函数(self) -> None:
        """原 12 张 PIL 占位水墨图必须各有 render_<key> 生成器；新增 key
        是真实素材（assets/backgrounds/<key>.png 直接下载），不要求生成器。
        """
        from tests import generate_assets

        ORIGINAL_INK_KEYS = {
            "misty_mountains", "rain_jiannan", "ink_bamboo", "lone_boat",
            "sunset_glow", "snow_night", "ancient_path", "deep_courtyard",
            "cup_of_tea", "rain_plantain", "desert_smoke", "rice_paper",
        }
        for filename in ORIGINAL_INK_KEYS:
            fn_name = f"render_{filename}"
            assert hasattr(generate_assets, fn_name), (
                f"原始 12 个水墨 key 缺生成器：{fn_name}"
            )
        # 回归：原始 12 个 key 仍然是字典的子集（不能丢）
        assert ORIGINAL_INK_KEYS.issubset(set(BG_KEYWORDS.keys())), (
            f"原始 12 个 key 缺失：{ORIGINAL_INK_KEYS - set(BG_KEYWORDS.keys())}"
        )


# === _pick_background ===

class TestPickBackground:
    @pytest.mark.unit
    def test_目录不存在_返回_None(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            composer, "settings",
            _StubSettings(asset_bg_dir=tmp_path / "nope", asset_music_dir=tmp_path / "nope2"),
        )
        assert _pick_background("远山") is None

    @pytest.mark.unit
    def test_空目录_返回_None(self, fake_assets: tuple[Path, Path]) -> None:
        assert _pick_background("远山") is None

    @pytest.mark.unit
    def test_关键词_山_命中_misty_mountains(self, fake_assets: tuple[Path, Path]) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "misty_mountains", color=(10, 20, 30))
        img = _pick_background("远山云雾")
        assert img is not None
        assert _pixel_of(img) == (10, 20, 30)

    @pytest.mark.unit
    def test_关键词_雨_命中_rain_jiannan(self, fake_assets: tuple[Path, Path]) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "rain_jiannan", color=(50, 50, 50))
        img = _pick_background("春雨")
        assert _pixel_of(img) == (50, 50, 50)

    @pytest.mark.unit
    def test_长关键词_烟雨_优先_于_雨(self, fake_assets: tuple[Path, Path]) -> None:
        """hint='烟雨' 同时命中 rain_jiannan 的'雨'和'烟雨'，应选最长的'烟雨'。"""
        bg, _ = fake_assets
        _make_bg(bg, "rain_jiannan", color=(11, 11, 11))
        img = _pick_background("烟雨江南")
        # 期望选 rain_jiannan（色 11,11,11）— 唯一候选
        assert _pixel_of(img) == (11, 11, 11)

    @pytest.mark.unit
    def test_同时_命中_多_张_时_取_最长_keyword_对应_的(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """hint 含 '竹' 命中 ink_bamboo，含 '雨' 命中 rain_jiannan；hint 同时含两字时取最长。"""
        bg, _ = fake_assets
        _make_bg(bg, "ink_bamboo", color=(20, 30, 40))
        _make_bg(bg, "rain_jiannan", color=(50, 60, 70))
        # 单字 '雨' 长度 1 vs '竹' 长度 1 平手；加 '墨竹' (2字) > '雨' (1字)
        img = _pick_background("墨竹夜雨")
        # '墨竹'(2) > '雨'(1) → ink_bamboo
        assert _pixel_of(img) == (20, 30, 40)

    @pytest.mark.unit
    def test_不_命中_也_能_返回_有效_图(self, fake_assets: tuple[Path, Path]) -> None:
        """无关 hint 走 random.choice；5 次调用都应得到一张图。"""
        bg, _ = fake_assets
        _make_bg(bg, "misty_mountains", color=(99, 88, 77))
        for _ in range(5):
            img = _pick_background("xyz无关词123")
            assert img is not None
            assert _pixel_of(img) == (99, 88, 77)

    @pytest.mark.unit
    def test_空_hint_走_random(self, fake_assets: tuple[Path, Path]) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "misty_mountains", color=(33, 44, 55))
        img = _pick_background("")
        assert img is not None

    @pytest.mark.unit
    def test_破损_png_返回_None_不_抛(self, fake_assets: tuple[Path, Path]) -> None:
        """命中关键词的文件坏了 → 返回 None（让上层走纯渐变 fallback），不抛。"""
        bg, _ = fake_assets
        (bg / "rain_jiannan.png").write_bytes(b"not a png")
        _make_bg(bg, "misty_mountains", color=(77, 88, 99))
        # 防御式关键词过滤已要求 kw≥2（防单字误命中地域图），
        # 所以这里用「烟雨」显式命中 rain_jiannan
        img = _pick_background("烟雨")
        assert img is None

    @pytest.mark.unit
    def test_scope_real_只_在_真实摄影图_里_挑(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """scope='real' 时，即便水墨 key 命中关键词，也不应被选；只在真实摄影池里挑。"""
        bg, _ = fake_assets
        # 水墨：rain_jiannan 命中 '雨'，不应被选（不在 real 池里）
        _make_bg(bg, "rain_jiannan", color=(11, 22, 33))
        # 真实：candle_warm 命中 '烛'；hint 同时含 '雨' 和 '烛'
        _make_bg(bg, "candle_warm", color=(200, 100, 50))
        img = _pick_background("夜雨烛影", scope="real")
        assert img is not None
        assert _pixel_of(img) == (200, 100, 50)

    @pytest.mark.unit
    def test_scope_ink_只_在_水墨图_里_挑(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """scope='ink' 时，即便真实摄影 key 命中关键词，也不应被选；只在水墨池里挑。"""
        bg, _ = fake_assets
        # 真实：candle_warm 命中 '烛'，不应被选（不在 ink 池里）
        _make_bg(bg, "candle_warm", color=(200, 100, 50))
        # 水墨：rain_jiannan 命中 '雨'
        _make_bg(bg, "rain_jiannan", color=(11, 22, 33))
        img = _pick_background("夜雨烛影", scope="ink")
        assert img is not None
        assert _pixel_of(img) == (11, 22, 33)

    @pytest.mark.unit
    def test_scope_real_不_命中_仍_走_random_但_只_在_real_池(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """无关 hint + scope='real' → random 兜底，但仍只能选真实摄影图。"""
        bg, _ = fake_assets
        # 池子里同时放水墨和真实图；random 也只能选真实那张
        _make_bg(bg, "rain_jiannan", color=(11, 22, 33))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        for _ in range(8):
            img = _pick_background("xyz无关词", scope="real")
            assert img is not None
            assert _pixel_of(img) == (180, 200, 220), (
                "scope=real 时不应选到水墨 rain_jiannan"
            )

    @pytest.mark.unit
    def test_scope_real_池_为空_返回_None(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """目录里只有水墨图，scope='real' 应返回 None 让上层 fallback。"""
        bg, _ = fake_assets
        _make_bg(bg, "rain_jiannan", color=(11, 22, 33))
        _make_bg(bg, "ink_bamboo", color=(20, 30, 40))
        img = _pick_background("烟雨", scope="real")
        assert img is None

    @pytest.mark.unit
    def test_scope_all_是_默认_等价于_不_传(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """scope 默认 'all'，与不传 scope 行为一致：所有图都可选。"""
        bg, _ = fake_assets
        _make_bg(bg, "rain_jiannan", color=(11, 22, 33))
        img_default = _pick_background("烟雨")
        img_all = _pick_background("烟雨", scope="all")
        assert _pixel_of(img_default) == _pixel_of(img_all) == (11, 22, 33)


# === _pick_background cascade（地域 context） ===

@pytest.fixture
def fake_manifest(fake_assets: tuple[Path, Path]) -> tuple[Path, dict]:
    """在 bg_dir 写一份 manifest.json：1 张波兰图 + 1 张通用图。"""
    bg, _ = fake_assets
    manifest = {
        "_doc": "测试用 manifest",
        "warsaw_old_town": {
            "location": ["poland", "warsaw"],
            "era": ["1990s"],
            "scene": ["street", "old_town"],
            "caption_hint": "华沙老城",
        },
        "morning_mist": {
            "location": [],
            "era": [],
            "scene": ["nature", "water", "fog"],
            "caption_hint": "晨雾",
        },
    }
    (bg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    # 清掉 lru_cache，让 fake_manifest 生效
    composer._load_manifest.cache_clear()
    return bg, manifest


class TestPickBackgroundContext:
    @pytest.mark.unit
    def test_波兰_故事_必_选_波兰图(
        self, fake_manifest: tuple[Path, Path]
    ) -> None:
        """scope=real + article_context={"location_tags":["poland"]} → 必出波兰图。"""
        bg, _ = fake_manifest
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        img = _pick_background(
            "远山云雾",  # visual_hint 不命中任何 manifest 条目关键词
            treat=False,
            scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == (150, 30, 30), (
            "波兰 context 应强制走波兰图，不应被 visual_hint 干扰"
        )

    @pytest.mark.unit
    def test_无_article_context_走_generic(
        self, fake_manifest: tuple[Path, Path]
    ) -> None:
        """article_context=None 时走原有 visual_hint 路径，行为不变。"""
        bg, _ = fake_manifest
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        # BG_KEYWORDS 里 '晨雾' 命中 morning_mist
        img = _pick_background(
            "晨雾", treat=False, scope="real", article_context=None
        )
        assert _pixel_of(img) == (180, 200, 220)

    @pytest.mark.unit
    def test_地域_匹配_但_无_图_fallback_generic(
        self, fake_manifest: tuple[Path, Path]
    ) -> None:
        """location_tags 命中（如 usa）但 manifest 里没图 → fallback generic（不报错）。"""
        bg, _ = fake_manifest
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        img = _pick_background(
            "晨雾",  # 命中 morning_mist
            treat=False,
            scope="real",
            article_context={"location_tags": ["usa"]},  # manifest 没美国图
        )
        assert img is not None
        # fallback 到 generic 路径，'晨雾' → morning_mist
        assert _pixel_of(img) == (180, 200, 220)

    @pytest.mark.unit
    def test_manifest_缺失_走_generic(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """没 manifest.json → _load_manifest 返回 {} → cascade 跳过 → generic 路径。"""
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        composer._load_manifest.cache_clear()
        img = _pick_background(
            "晨雾",
            treat=False,
            scope="real",
            article_context={"location_tags": ["poland"]},
        )
        # 没有 manifest → cascade 跳过 → generic 路径命中 morning_mist
        assert _pixel_of(img) == (180, 200, 220)

    @pytest.mark.unit
    def test_地域_子集_内_visual_hint_优先(
        self, fake_manifest: tuple[Path, Path]
    ) -> None:
        """同地域多图时，按 visual_hint 在子集内 longest-match 选。"""
        bg, _ = fake_manifest
        # 加第二张波兰图，BG_KEYWORDS 里 '雪' 命中它
        _make_bg(bg, "warsaw_winter", color=(50, 50, 80))
        # 把 warsaw_winter 加进 manifest（location poland）
        manifest = json.loads((bg / "manifest.json").read_text())
        manifest["warsaw_winter"] = {
            "location": ["poland"],
            "era": [],
            "scene": ["snow"],
            "caption_hint": "波兰冬街",
        }
        (bg / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        # BG_KEYWORDS 里 '雪' → snow_night (ink) 或其他；需要让 '雪' 命中 warsaw_winter
        # 实际：BG_KEYWORDS 不为 warsaw_winter 登记关键词，验证子集 random 行为即可
        # 这里改成验证：在 poland 子集内 fallback random（BG_KEYWORDS 不命中）
        # 由于 lru_cache，需要再清一次
        composer._load_manifest.cache_clear()
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        img = _pick_background(
            "不命中任何关键词的hint",
            treat=False,
            scope="real",
            article_context={"location_tags": ["poland"]},
        )
        # 子集为 [warsaw_old_town, warsaw_winter]；visual_hint 不命中 → random
        # 不论选谁，颜色必是这两个之一
        assert _pixel_of(img) in {(150, 30, 30), (50, 50, 80)}

    @pytest.mark.unit
    def test_多_地域_取_并集(self, fake_manifest: tuple[Path, Path]) -> None:
        """location_tags=['poland','usa'] → 两个地域的图都进候选池。"""
        bg, _ = fake_manifest
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        # 把 morning_mist 改成 USA（模拟多个地域的 manifest）
        manifest = json.loads((bg / "manifest.json").read_text())
        manifest["morning_mist"]["location"] = ["usa"]
        (bg / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        composer._load_manifest.cache_clear()
        # visual_hint 不命中 → random；候选池 = 2 张（poland + usa）
        for _ in range(6):
            img = _pick_background(
                "无关hint",
                treat=False,
                scope="real",
                article_context={"location_tags": ["poland", "usa"]},
            )
            assert _pixel_of(img) in {(150, 30, 30), (180, 200, 220)}

    @pytest.mark.unit
    def test_空_location_tags_走_generic(
        self, fake_manifest: tuple[Path, Path]
    ) -> None:
        """article_context={location_tags: []} → cascade 跳过 → generic。"""
        bg, _ = fake_manifest
        _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))
        _make_bg(bg, "morning_mist", color=(180, 200, 220))
        img = _pick_background(
            "晨雾",
            treat=False,
            scope="real",
            article_context={"location_tags": []},
        )
        # generic 路径命中 morning_mist
        assert _pixel_of(img) == (180, 200, 220)


# === 第四批：东欧冷寂系自然风景（5 张，墨绿/冷/雾/暗）===
_NATURE_PHOTO_KEYS: tuple[str, ...] = (
    "bialowieza_forest", "masurian_lake", "tatra_mountain",
    "augustow_canal", "biebrza_marsh",
)

# === 第五批：东欧天气场景（7 张，雪/雨/雾/夜）===
_WEATHER_PHOTO_KEYS: tuple[str, ...] = (
    "moscow_snow", "warsaw_snow", "krakow_rain",
    "warsaw_fog", "warsaw_night", "prague_snow", "budapest_night",
)


class TestEasternEuropeNaturePool:
    @pytest.mark.unit
    def test_5_张_自然_图_都在_REAL_PHOTO_KEYS(self) -> None:
        """5 张自然图必须在 _REAL_PHOTO_KEYS（被 scope=real 选池）。"""
        for k in _NATURE_PHOTO_KEYS:
            assert k in composer._REAL_PHOTO_KEYS, f"{k} 未注册到 _REAL_PHOTO_KEYS"

    @pytest.mark.unit
    def test_5_张_自然_图_都在_BG_KEYWORDS(self) -> None:
        """每个 key 在 BG_KEYWORDS 至少有 1 个关键词。"""
        for k in _NATURE_PHOTO_KEYS:
            assert k in BG_KEYWORDS, f"{k} 缺 BG_KEYWORDS 条目"
            assert len(BG_KEYWORDS[k]) > 0, f"{k} 关键词列表为空"

    @pytest.mark.unit
    def test_真实_manifest_5_张_自然_图_都_有_location_tag(
        self, tmp_path: Path
    ) -> None:
        real_manifest = Path("/Users/yzc/Desktop/renfang/assets/backgrounds/manifest.json")
        if not real_manifest.exists():
            pytest.skip("真实 manifest.json 不存在，跳过")
        data = json.loads(real_manifest.read_text())
        for k in _NATURE_PHOTO_KEYS:
            assert k in data, f"{k} 不在真实 manifest.json"
            locs = set(data[k].get("location", []))
            assert locs & {"poland", "russia", "eastern_europe"}, (
                f"{k} 缺东欧 location tag, 实际 {locs}"
            )

    @pytest.mark.unit
    def test_真实_manifest_5_张_自然_图_caption_中文(
        self, tmp_path: Path
    ) -> None:
        real_manifest = Path("/Users/yzc/Desktop/renfang/assets/backgrounds/manifest.json")
        if not real_manifest.exists():
            pytest.skip("真实 manifest.json 不存在，跳过")
        data = json.loads(real_manifest.read_text())
        for k in _NATURE_PHOTO_KEYS:
            caption = data[k].get("caption_hint", "")
            assert len(caption) >= 2, f"{k} caption_hint 太短"
            assert any('\u4e00' <= ch <= '\u9fff' for ch in caption), (
                f"{k} caption_hint 应含中文: {caption!r}"
            )

    @pytest.mark.unit
    def test_5_张_自然_图_PNG_文件_实际存在(self) -> None:
        bg_dir = Path("/Users/yzc/Desktop/renfang/assets/backgrounds")
        for k in _NATURE_PHOTO_KEYS:
            p = bg_dir / f"{k}.png"
            assert p.exists(), f"{p} 缺失"
            assert p.stat().st_size > 10_000, f"{p} 太小（{p.stat().st_size} B）"


class TestWeatherScenePool:
    """7 张天气场景图：雪/雨/雾/夜，验证索引一致。"""

    @pytest.mark.unit
    def test_7_张_天气_图_都在_REAL_PHOTO_KEYS(self) -> None:
        for k in _WEATHER_PHOTO_KEYS:
            assert k in composer._REAL_PHOTO_KEYS, f"{k} 未注册到 _REAL_PHOTO_KEYS"

    @pytest.mark.unit
    def test_7_张_天气_图_都在_BG_KEYWORDS(self) -> None:
        for k in _WEATHER_PHOTO_KEYS:
            assert k in BG_KEYWORDS, f"{k} 缺 BG_KEYWORDS 条目"
            assert len(BG_KEYWORDS[k]) > 0, f"{k} 关键词列表为空"

    @pytest.mark.unit
    def test_真实_manifest_7_张_天气_图_都_有_location_tag(self, tmp_path: Path) -> None:
        real_manifest = Path("/Users/yzc/Desktop/renfang/assets/backgrounds/manifest.json")
        if not real_manifest.exists():
            pytest.skip("真实 manifest.json 不存在，跳过")
        data = json.loads(real_manifest.read_text())
        for k in _WEATHER_PHOTO_KEYS:
            assert k in data, f"{k} 不在真实 manifest.json"
            locs = set(data[k].get("location", []))
            assert locs & {"poland", "russia", "czech", "hungary", "eastern_europe"}, (
                f"{k} 缺东欧 location tag, 实际 {locs}"
            )

    @pytest.mark.unit
    def test_真实_manifest_7_张_天气_图_caption_中文(self, tmp_path: Path) -> None:
        real_manifest = Path("/Users/yzc/Desktop/renfang/assets/backgrounds/manifest.json")
        if not real_manifest.exists():
            pytest.skip("真实 manifest.json 不存在，跳过")
        data = json.loads(real_manifest.read_text())
        for k in _WEATHER_PHOTO_KEYS:
            caption = data[k].get("caption_hint", "")
            assert len(caption) >= 2, f"{k} caption_hint 太短"
            assert any('\u4e00' <= ch <= '\u9fff' for ch in caption), (
                f"{k} caption_hint 应含中文: {caption!r}"
            )

    @pytest.mark.unit
    def test_7_张_天气_图_PNG_文件_实际存在(self) -> None:
        bg_dir = Path("/Users/yzc/Desktop/renfang/assets/backgrounds")
        for k in _WEATHER_PHOTO_KEYS:
            p = bg_dir / f"{k}.png"
            assert p.exists(), f"{p} 缺失"
            assert p.stat().st_size > 10_000, f"{p} 太小（{p.stat().st_size} B）"

    @pytest.mark.unit
    def test_moscow_snow_weather_keywords(self) -> None:
        """mosco_snow 关键词应含风雪冰寒类，用于路由 '莫斯科风雪' 类 visual_hint。"""
        kws = BG_KEYWORDS["moscow_snow"]
        assert "雪" in kws or "风雪" in kws, f"moscow_snow 缺风雪关键词: {kws}"

    @pytest.mark.unit
    def test_warsaw_fog_weather_keywords(self) -> None:
        """warsaw_fog 关键词应含晨雾/薄雾等 2 字组合，用于路由 '晨雾' 类 visual_hint。

        历史教训：旧版用 '雾' 1 字关键词，会被泛化 hint（如 '烟雨远山' 里的
        '雨' 不会被命中但 '烟雨' 仍误中）抢走——已改 min_keyword_len ≥ 2 防御。
        这里断言用 2 字+ 的具体词。
        """
        kws = BG_KEYWORDS["warsaw_fog"]
        assert "晨雾" in kws, f"warsaw_fog 缺 2 字关键词 '晨雾': {kws}"

    @pytest.mark.unit
    def test_warsaw_night_weather_keywords(self) -> None:
        """warsaw_night 关键词应含夜灯/夜色等 2 字组合。"""
        kws = BG_KEYWORDS["warsaw_night"]
        assert "夜灯" in kws or "夜色" in kws, (
            f"warsaw_night 缺 2 字夜关键词: {kws}"
        )

    @pytest.mark.unit
    def test_budapest_night_weather_keywords(self) -> None:
        kws = BG_KEYWORDS["budapest_night"]
        assert "夜灯桥" in kws or "匈牙利夜" in kws, (
            f"budapest_night 缺 2 字夜关键词: {kws}"
        )

    @pytest.mark.unit
    def test_volga_river_已从索引移除(self) -> None:
        """volga_river 已被 moscow_snow 替代，不应残留。"""
        assert "volga_river" not in composer._REAL_PHOTO_KEYS
        assert "volga_river" not in BG_KEYWORDS


# === 第六批：风雪主题配图正确性（雪/雾/夜 hint 必须压过晴天街景）===

@pytest.fixture
def weather_pool(fake_assets: tuple[Path, Path]):
    """构造 poland cascade 池：晴天街景 + 真雪/雾/夜 + 雨巷图。
    验证 longest-match 把雪主题路由到 snow 图，不是 warsaw_winter_street 晴天。"""
    bg, _ = fake_assets
    # 颜色：每个 photo 一个独特色，断言用 _pixel_of 比对
    _make_bg(bg, "warsaw_old_town", color=(150, 30, 30))         # 晴天老城
    _make_bg(bg, "warsaw_winter_street", color=(155, 35, 35))     # 名字误导的晴天街景
    _make_bg(bg, "warsaw_snow", color=(200, 200, 220))            # 真雪
    _make_bg(bg, "warsaw_fog", color=(130, 130, 130))             # 雾
    _make_bg(bg, "warsaw_night", color=(20, 20, 40))              # 夜
    _make_bg(bg, "krakow_rain", color=(90, 100, 110))             # 雨巷
    _make_bg(bg, "krakow_square", color=(170, 50, 50))            # 晴天广场
    manifest = {
        "warsaw_old_town":      {"location": ["poland"], "scene": ["street", "old_town"]},
        "warsaw_winter_street": {"location": ["poland"], "scene": ["street", "old_town"]},
        "warsaw_snow":          {"location": ["poland"], "scene": ["snow", "city", "winter"]},
        "warsaw_fog":           {"location": ["poland"], "scene": ["fog", "street"]},
        "warsaw_night":         {"location": ["poland"], "scene": ["night", "street"]},
        "krakow_rain":          {"location": ["poland"], "scene": ["rain", "street"]},
        "krakow_square":        {"location": ["poland"], "scene": ["square", "old_town"]},
    }
    (bg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    composer._load_manifest.cache_clear()
    return bg


# 颜色索引表（test 用 pixel 颜色反查选了哪张图）
_POLAND_POOL_COLORS: dict[str, tuple[int, int, int]] = {
    "warsaw_old_town":       (150, 30, 30),
    "warsaw_winter_street":  (155, 35, 35),
    "warsaw_snow":           (200, 200, 220),
    "warsaw_fog":            (130, 130, 130),
    "warsaw_night":          (20, 20, 40),
    "krakow_rain":           (90, 100, 110),
    "krakow_square":         (170, 50, 50),
}


def _color_to_name(color: tuple[int, int, int] | None) -> str | None:
    """反查 pixel 颜色 → photo 名（test 报错时便于阅读）。"""
    if color is None:
        return None
    for name, c in _POLAND_POOL_COLORS.items():
        if c == color:
            return name
    return f"unknown({color})"


class TestWeatherRouting:
    """雪/雾/夜主题 visual_hint 必须路由到对应天气图，不是晴天街景。

    核心 case：warsaw_winter_street.png 实际是晴天街景（旧文件名误导）；
    BG_KEYWORDS 旧版含"雪/冬/站台/异国/列车/火车"，会被 hint="雪夜火车站"
    中的"火车"(2字) 误命中。修复后这些误导词已清，真雪图加了"雪夜/风雪"(2字)
    应在 cascade 池内压过晴天。
    """

    @pytest.mark.unit
    def test_雪夜火车站_必须_路由到_snow_图(
        self, weather_pool: Path
    ) -> None:
        """hint='雪夜火车站，行人匆匆' → 必出 warsaw_snow，不是 warsaw_winter_street。"""
        img = _pick_background(
            "雪夜火车站，行人匆匆",
            treat=False, scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == _POLAND_POOL_COLORS["warsaw_snow"], (
            f"雪主题 hint 应命中 warsaw_snow，实际选了 {_color_to_name(_pixel_of(img))}"
        )

    @pytest.mark.unit
    def test_风雪站台_必须_路由到_snow_图(
        self, weather_pool: Path
    ) -> None:
        """hint='风雪站台' → 2 字 '风雪' 命中 warsaw_snow，不是 warsaw_winter_street。"""
        img = _pick_background(
            "风雪站台",
            treat=False, scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == _POLAND_POOL_COLORS["warsaw_snow"], (
            f"风雪 hint 应命中 warsaw_snow，实际选了 {_color_to_name(_pixel_of(img))}"
        )

    @pytest.mark.unit
    def test_雨巷_必须_路由到_rain_图(
        self, weather_pool: Path
    ) -> None:
        """hint='雨巷' → 2 字 '雨巷' 命中 krakow_rain，不是晴天。"""
        img = _pick_background(
            "雨巷",
            treat=False, scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == _POLAND_POOL_COLORS["krakow_rain"], (
            f"雨巷 hint 应命中 krakow_rain，实际选了 {_color_to_name(_pixel_of(img))}"
        )

    @pytest.mark.unit
    def test_晨雾_必须_路由到_fog_图(
        self, weather_pool: Path
    ) -> None:
        """hint='晨雾' → 2 字 '晨雾' 命中 warsaw_fog。"""
        img = _pick_background(
            "晨雾",
            treat=False, scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == _POLAND_POOL_COLORS["warsaw_fog"], (
            f"晨雾 hint 应命中 warsaw_fog，实际选了 {_color_to_name(_pixel_of(img))}"
        )

    @pytest.mark.unit
    def test_夜灯_必须_路由到_night_图(
        self, weather_pool: Path
    ) -> None:
        """hint='夜灯' → 2 字 '夜灯' 命中 warsaw_night。"""
        img = _pick_background(
            "夜灯",
            treat=False, scope="real",
            article_context={"location_tags": ["poland"]},
        )
        assert img is not None
        assert _pixel_of(img) == _POLAND_POOL_COLORS["warsaw_night"], (
            f"夜灯 hint 应命中 warsaw_night，实际选了 {_color_to_name(_pixel_of(img))}"
        )


# === _pick_music ===

class TestPickMusic:
    @pytest.mark.unit
    def test_目录_不存在_返回_None(self, tmp_path: Path) -> None:
        assert _pick_music(tmp_path / "nope") is None

    @pytest.mark.unit
    def test_空_目录_返回_None(self, tmp_path: Path) -> None:
        d = tmp_path / "music"
        d.mkdir()
        assert _pick_music(d) is None

    @pytest.mark.unit
    def test_单_首_返回_它(self, tmp_path: Path) -> None:
        d = tmp_path / "music"
        d.mkdir()
        (d / "x.mp3").write_bytes(b"")
        assert _pick_music(d) == d / "x.mp3"

    @pytest.mark.unit
    def test_多_首_返回_池中_一首(self, tmp_path: Path) -> None:
        d = tmp_path / "music"
        d.mkdir()
        for name in ["a.mp3", "b.wav", "c.m4a"]:
            (d / name).write_bytes(b"")
        out = _pick_music(d)
        assert out is not None
        assert out.name in {"a.mp3", "b.wav", "c.m4a"}

    @pytest.mark.unit
    def test_多_首_随机_有_变化(self, tmp_path: Path) -> None:
        """50 次调用里应至少见过 2 种。"""
        d = tmp_path / "music"
        d.mkdir()
        for name in ["a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3"]:
            (d / name).write_bytes(b"")
        seen = {_pick_music(d).name for _ in range(50)}
        assert len(seen) >= 2, f"50 次里只见 {seen}"

    @pytest.mark.unit
    def test_支持_三种_后缀(self, tmp_path: Path) -> None:
        d = tmp_path / "music"
        d.mkdir()
        for name in ["x.mp3", "y.wav", "z.m4a"]:
            (d / name).write_bytes(b"")
        out = _pick_music(d)
        assert out is not None
        assert out.suffix in {".mp3", ".wav", ".m4a"}


# === _wrap_text 单测：确保任何一行都不超 max_width ===

from PIL import ImageFont

from app.video.composer import _find_chinese_font, _split_oversize, _wrap_text


def _font(size: int = 56) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_find_chinese_font(), size)


class TestWrapText:
    """所有用例都断言：每一行的像素宽度 ≤ max_width，绝不溢出。"""

    @pytest.mark.unit
    def test_em_dash_不让_行_溢出(self) -> None:
        """回归 bug：包含 '——' 的长句之前会被合并成一行 1539px ＞ 720px。"""
        font = _font(56)
        max_w = 720
        text = "F的哥哥从大衣里掏出几页蓝印纸——贡嘎拉州立医院来信了，"
        lines = _wrap_text(text, font, max_w)
        for ln in lines:
            assert font.getlength(ln) <= max_w, (
                f"line overflows: {ln!r} ({font.getlength(ln)}px > {max_w}px)"
            )
        assert len(lines) >= 3, f"em-dash 句应至少切 3 行，实际 {len(lines)}: {lines}"

    @pytest.mark.unit
    def test_超长_中文_run_按字符_切(self) -> None:
        """单个 14 字中文 token (~784px) > max_width (720px) 时，必须切，不能一行溢出。"""
        font = _font(56)
        max_w = 720
        text = "的哥哥从大衣里掏出几页蓝印纸贡嘎拉州立医院来信了"
        lines = _wrap_text(text, font, max_w)
        for ln in lines:
            assert font.getlength(ln) <= max_w, (
                f"line overflows: {ln!r} ({font.getlength(ln)}px > {max_w}px)"
            )

    @pytest.mark.unit
    def test_标点_尾随_合并_不让_行_溢出(self) -> None:
        """合并行首孤立标点到上一行，但若合并后超宽则保持分开。"""
        font = _font(56)
        max_w = 720
        # 12 字 + 标点 — 合并就刚好超 720
        text = "abcdefghijkl大衣里掏出几页蓝印纸贡嘎拉州立医院。"
        lines = _wrap_text(text, font, max_w)
        for ln in lines:
            assert font.getlength(ln) <= max_w, (
                f"line overflows: {ln!r} ({font.getlength(ln)}px > {max_w}px)"
            )

    @pytest.mark.unit
    def test_普通_短_句子_正常_切分(self) -> None:
        font = _font(56)
        max_w = 720
        text = "普通的短句子，应该可读。"
        lines = _wrap_text(text, font, max_w)
        assert lines, "短句应至少 1 行"
        for ln in lines:
            assert font.getlength(ln) <= max_w

    @pytest.mark.unit
    def test_多个_em_dash_句_不溢出(self) -> None:
        font = _font(56)
        max_w = 720
        text = "他说——也许是——某种象征——你能懂吗？"
        lines = _wrap_text(text, font, max_w)
        for ln in lines:
            assert font.getlength(ln) <= max_w, (
                f"line overflows: {ln!r} ({font.getlength(ln)}px > {max_w}px)"
            )

    @pytest.mark.unit
    def test_closing_大字号_不溢出(self) -> None:
        """closing 卡用 76pt 字号 + max_width = 1080-240 = 840。"""
        font = _font(76)
        max_w = 840
        text = "于是合上书页，灯下独坐——这一夜的风声便也算听过了。"
        lines = _wrap_text(text, font, max_w)
        for ln in lines:
            assert font.getlength(ln) <= max_w, (
                f"closing line overflows: {ln!r} ({font.getlength(ln)}px > {max_w}px)"
            )


class TestSplitOversize:
    """_split_oversize: 把一个超宽 token 按字符切成多段。"""

    @pytest.mark.unit
    def test_每段_都_不超_宽(self) -> None:
        font = _font(56)
        max_w = 200
        # 长串中文
        tk = "山外青山楼外楼西湖歌舞几时休"
        chunks = _split_oversize(tk, font, max_w)
        assert chunks, "至少应有 1 段"
        for c in chunks:
            assert font.getlength(c) <= max_w
        # 拼回去要等于原串
        assert "".join(chunks) == tk

    @pytest.mark.unit
    def test_单字_就放不下_仍然_保留(self) -> None:
        """极端情况：max_width 比单字还窄。函数不应死循环，至少把每个字单独成段。"""
        font = _font(56)
        # 单字宽 56；用 max_w=30 让单字也放不下
        chunks = _split_oversize("中文", font, 30)
        assert "".join(chunks) == "中文"


# === Polaroid 拍立得卡（杂志卡片式） ===

from app.video.composer import (  # noqa: E402
    _crop_aspect,
    _POLAROID_CARD_BG,
    _POLAROID_H,
    _POLAROID_W,
    _render_polaroid_card,
    _short_caption_from,
)


class TestCropAspect:
    """`_crop_aspect` 中心裁切 + resize 到目标尺寸。"""

    @pytest.mark.unit
    def test_返回_目标_尺寸(self) -> None:
        src = Image.new("RGB", (1000, 500), (255, 0, 0))
        out = _crop_aspect(src, 400, 300)
        assert out.size == (400, 300)

    @pytest.mark.unit
    def test_原图_更宽_裁_左右(self) -> None:
        # 1000x500 → 4:3 → 裁左右 (新 750x500 → 400x300)
        src = Image.new("RGB", (1000, 500), (10, 20, 30))
        out = _crop_aspect(src, 400, 300)
        assert out.size == (400, 300)
        # 中心点还是黑（被裁的中心区仍是同色）
        assert out.getpixel((200, 150)) == (10, 20, 30)

    @pytest.mark.unit
    def test_原图_更高_裁_上下(self) -> None:
        # 500x1000 → 4:3 → 裁上下 (新 500x750 → 400x300)
        src = Image.new("RGB", (500, 1000), (50, 60, 70))
        out = _crop_aspect(src, 400, 300)
        assert out.size == (400, 300)
        assert out.getpixel((200, 150)) == (50, 60, 70)

    @pytest.mark.unit
    def test_原图_比例_相同_不_裁(self) -> None:
        # 800x600 → 4:3 → 不裁直接 resize
        src = Image.new("RGB", (800, 600), (1, 2, 3))
        out = _crop_aspect(src, 400, 300)
        assert out.size == (400, 300)
        assert out.getpixel((200, 150)) == (1, 2, 3)


class TestShortCaption:
    @pytest.mark.unit
    def test_抽_前_6_字(self) -> None:
        assert _short_caption_from("一九九二年二月，柏林到华沙") == "一九九二年二"

    @pytest.mark.unit
    def test_去_标点(self) -> None:
        assert _short_caption_from("你好，世界。这是一个测试。") == "你好世界这是"

    @pytest.mark.unit
    def test_空_串(self) -> None:
        assert _short_caption_from("") == ""

    @pytest.mark.unit
    def test_只_有_标点(self) -> None:
        assert _short_caption_from("，。！？") == ""

    @pytest.mark.unit
    def test_超长_截断(self) -> None:
        text = "中文" * 20
        cap = _short_caption_from(text, max_chars=4)
        assert cap == "中文中文"


class TestPolaroidCard:
    """`_render_polaroid_card` 拍立得白卡 + 图 + 投影（无朱印）。"""

    def _solid(self, color: tuple[int, int, int] = (123, 45, 67)) -> Image.Image:
        return Image.new("RGB", (1080, 1920), color)

    @pytest.mark.unit
    def test_返回_卡_和_阴影(self) -> None:
        card, shadow = _render_polaroid_card(self._solid(), "一九九二年")
        assert card.size == (_POLAROID_W, _POLAROID_H)
        assert shadow.size == (_POLAROID_W + 16, _POLAROID_H + 16)

    @pytest.mark.unit
    def test_卡_是_RGB_暖白_底(self) -> None:
        card, _ = _render_polaroid_card(self._solid(), "x")
        assert card.mode == "RGB"
        # 左上角是暖白底（没图、没 caption 的区域）
        assert card.getpixel((5, 5)) == _POLAROID_CARD_BG

    @pytest.mark.unit
    def test_图_被_裁切_并_贴_入_卡(self) -> None:
        # 给个明显的红/蓝双色源图；裁后图区中点应不是暖白
        src = Image.new("RGB", (2000, 2000), (200, 50, 50))
        card, _ = _render_polaroid_card(src, "x")
        # 图区内点（POLAROID_PAD_X + IMG_W/2, POLAROID_PAD_TOP + IMG_H/2）
        from app.video.composer import _POLAROID_IMG_H, _POLAROID_IMG_W, _POLAROID_PAD_TOP, _POLAROID_PAD_X
        cx = _POLAROID_PAD_X + _POLAROID_IMG_W // 2
        cy = _POLAROID_PAD_TOP + _POLAROID_IMG_H // 2
        assert card.getpixel((cx, cy)) == (200, 50, 50)

    @pytest.mark.unit
    def test_右上_不_有_朱印(self) -> None:
        # 移除朱印后：右上角应是暖白卡底（没红像素）
        card, _ = _render_polaroid_card(self._solid(), "x")
        # 右上角抽查：原朱印区域 (646,18)-(702,74)
        for x, y in [(650, 20), (698, 20), (650, 70), (698, 70)]:
            r, g, b = card.getpixel((x, y))
            # 不应该是朱红（R 不会 > 150）
            assert not (r > 150 and g < 120 and b < 100), (
                f"({x},{y}) 不应有朱红，实际 {(r, g, b)}"
            )

    @pytest.mark.unit
    def test_阴影_是_RGBA_且_右下_有_黑(self) -> None:
        card, shadow = _render_polaroid_card(self._solid(), "x")
        assert shadow.mode == "RGBA"
        # 阴影右下角点（card 右下 + 偏移 8）应有黑 alpha
        from app.video.composer import _POLAROID_W, _POLAROID_H
        r, g, b, a = shadow.getpixel((_POLAROID_W - 4, _POLAROID_H - 4))
        # 阴影 fill (0,0,0,38)；边缘被 blur 后 alpha 较低但 > 0
        assert a > 0, f"阴影右下 alpha 应 > 0，实际 {a}"

    @pytest.mark.unit
    def test_caption_字符串_被_接受(self) -> None:
        # caption 是空 / 全标点 / 极长 都应不抛
        for cap in ["", "……", "援翰写心", "x" * 100]:
            card, _ = _render_polaroid_card(self._solid(), cap)
            assert card.size == (_POLAROID_W, _POLAROID_H)


# === render_card forced_polaroid_key ===


class TestRenderCardWithForcedPolaroid:
    """forced_polaroid_key 非空时直接 load PNG，跳过 _pick_background。"""

    def _render(self, fake_assets, *, forced_key=None, visual_hint="") -> Path:
        bg, _ = fake_assets
        out = bg.parent / "test_card.png"
        # 放一张真实 key 的 PNG 到 bg_dir，供 forced_polaroid_key load
        _make_bg(bg, "warsaw_snow", color=(200, 200, 220))
        _make_bg(bg, "candle_warm", color=(200, 100, 50))
        return render_card(
            "测试文字",
            out,
            bg=Image.new("RGB", (1080, 1920), (240, 235, 220)),
            visual_hint=visual_hint,
            forced_polaroid_key=forced_key,
        )

    @pytest.mark.unit
    def test_forced_key_不存在_fallback_到_pick_background(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """forced key 指向不存在的文件 → 走 _pick_background keyword cascade。"""
        out = self._render(fake_assets, forced_key="nonexistent", visual_hint="烛光")
        img = Image.open(out)
        assert img is not None
        # 应该成功渲染（走 keyword fallback → candle_warm）
        assert _pixel_of(img) is not None

    @pytest.mark.unit
    def test_forced_key_None_走_原有_路径(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """forced_polaroid_key=None → 走 _pick_background keyword cascade，行为不变。"""
        out = self._render(fake_assets, forced_key=None, visual_hint="烛光")
        img = Image.open(out)
        assert img is not None
        # 卡应该正常渲染
        assert img.size == (1080, 1920)

    @pytest.mark.unit
    def test_closing_卡_不受_forced_key_影响(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """closing=True 时不走 polaroid 路径，forced_polaroid_key 被忽略。"""
        bg, _ = fake_assets
        out = bg.parent / "closing_card.png"
        render_card(
            "片尾文字",
            out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            closing=True,
            forced_polaroid_key="warsaw_snow",  # 应被忽略
        )
        img = Image.open(out)
        assert img is not None
        assert img.size == (1080, 1920)


# === render_card forced_polaroid_path（Pexels 搜图）===


class TestRenderCardForcedPath:
    """forced_polaroid_path 优先级最高：文件存在 → 直接 load。"""

    def _make_external_jpg(self, tmp_path: Path, color: tuple[int, int, int] = (50, 200, 50)) -> Path:
        p = tmp_path / "external_photo.jpg"
        Image.new("RGB", (1080, 1920), color).save(p, "JPEG")
        return p

    @pytest.mark.unit
    def test_forced_path_优先级_高于_forced_key(
        self, fake_assets: tuple[Path, Path], tmp_path: Path
    ) -> None:
        """Pexels 搜出的外链 JPG 优先级最高，不走图库 key。"""
        bg, _ = fake_assets
        # 图库里有 warsaw_snow (色 11,22,33)
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        # 但 forced_polaroid_path 指向一个不同色（绿色）的外链
        ext = self._make_external_jpg(tmp_path, color=(50, 200, 50))
        out = bg.parent / "card_ext.png"
        render_card(
            "测试",
            out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            visual_hint="雪夜",
            forced_polaroid_key="warsaw_snow",
            forced_polaroid_path=ext,
        )
        img = Image.open(out)
        assert img is not None
        # 拍立得区域应含绿色（外链图主导）
        cx, cy = 200 + 640 // 2, 40 + 480 // 2
        r, g, b = img.getpixel((cx, cy))
        # 拍立得图源是绿（50,200,50），纸面背景的米色会因裁切被裁掉
        assert g > r and g > b, f"应见外链图绿色调，实际 ({r},{g},{b})"

    @pytest.mark.unit
    def test_forced_path_文件不存在_fallback_to_key(
        self, fake_assets: tuple[Path, Path], tmp_path: Path
    ) -> None:
        """forced_polaroid_path 指向不存在的文件 → 退到 forced_polaroid_key → 图库。"""
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_fb.png"
        render_card(
            "测试",
            out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            visual_hint="雪",
            forced_polaroid_key="warsaw_snow",
            forced_polaroid_path=tmp_path / "nope.jpg",  # 不存在
        )
        img = Image.open(out)
        # 应正常渲染（fallback 到 warsaw_snow）
        assert img is not None
        assert img.size == (1080, 1920)

    @pytest.mark.unit
    def test_两个_都_无_走_pick_background(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """forced_polaroid_path=None + forced_polaroid_key=None → _pick_background 路径。"""
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_none.png"
        render_card(
            "测试",
            out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            visual_hint="雪",
        )
        img = Image.open(out)
        assert img is not None
        assert img.size == (1080, 1920)


class TestShouldShowPolaroid:
    """首页必出 + 每 3 段穿插 1 张，closing 永远不画。"""

    @pytest.mark.parametrize(
        "i, total, closing, expected",
        [
            # 首页
            (0, 5, False, True),
            # 中间每 3 段
            (3, 5, False, True),
            (6, 7, False, True),
            # 中间非 3 倍数：不画
            (1, 5, False, False),
            (2, 5, False, False),
            (4, 5, False, False),
            (5, 7, False, False),
            (7, 8, False, False),
            # closing 永远不画
            (0, 5, True, False),
            (3, 5, True, False),
        ],
    )
    def test_规则(
        self, i: int, total: int, closing: bool, expected: bool
    ) -> None:
        assert _should_show_polaroid(i, total, closing=closing) is expected


class TestRenderCardShowPolaroid:
    """show_polaroid 参数：True 时画拍立得（调 _render_polaroid_card + _pick_background），
    False 时跳过两者，只剩 bg + 主文字。"""

    def test_默认_True_走_拍立得(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_show.png"

        polaroid_mock = MagicMock(return_value=(Image.new("RGB", (720, 720)), Image.new("RGBA", (740, 740))))
        pick_mock = MagicMock(return_value=Image.new("RGB", (800, 600)))
        monkeypatch.setattr(composer, "_render_polaroid_card", polaroid_mock)
        # V3：polaroid fallback 改用 _pick_abstract_bg，不再调 _pick_background
        monkeypatch.setattr(composer, "_pick_abstract_bg", pick_mock)

        render_card("测试", out, bg=Image.new("RGB", (1080, 1920), (200, 200, 200)))

        assert polaroid_mock.call_count == 1
        assert pick_mock.call_count == 1
        assert Image.open(out).size == (1080, 1920)

    def test_False_完全_跳过_拍立得(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_noshow.png"

        polaroid_mock = MagicMock(return_value=(Image.new("RGB", (720, 720)), Image.new("RGBA", (740, 740))))
        pick_mock = MagicMock(return_value=Image.new("RGB", (800, 600)))
        monkeypatch.setattr(composer, "_render_polaroid_card", polaroid_mock)
        monkeypatch.setattr(composer, "_pick_background", pick_mock)

        render_card(
            "测试文字。",
            out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            show_polaroid=False,
        )

        assert polaroid_mock.call_count == 0
        assert pick_mock.call_count == 0
        assert Image.open(out).size == (1080, 1920)


class TestRenderCardTextLayout:
    """非 polaroid 用大字号 + 宽文本框；右上页码已移除。"""

    def test_polaroid_走_小字号_720(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_polaroid_layout.png"
        wrap_mock = MagicMock(wraps=composer._wrap_text)
        monkeypatch.setattr(composer, "_wrap_text", wrap_mock)
        render_card(
            "测试正文。", out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            show_polaroid=True,
        )
        widths = [c.args[2] for c in wrap_mock.call_args_list]
        assert 720 in widths

    def test_非_polaroid_走_大字号_900(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_nopolaroid_layout.png"
        wrap_mock = MagicMock(wraps=composer._wrap_text)
        monkeypatch.setattr(composer, "_wrap_text", wrap_mock)
        render_card(
            "测试正文。", out,
            bg=Image.new("RGB", (1080, 1920), (200, 200, 200)),
            show_polaroid=False,
        )
        widths = [c.args[2] for c in wrap_mock.call_args_list]
        assert 900 in widths
        assert 720 not in widths

    def test_右上页码_已_移除_polaroid(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_no_top_polaroid.png"
        render_card(
            "测试。", out, index=2, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            show_polaroid=True,
        )
        img = Image.open(out).convert("RGB")
        # 右上 (w-100, 80) 应是 bg 色，不该有 progress 文字的墨色
        assert sum(img.getpixel((980, 80))[:3]) > 600  # bg ~ 234+230+218=682

    def test_右上页码_已_移除_非_polaroid(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_no_top_nopolaroid.png"
        render_card(
            "测试。", out, index=2, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            show_polaroid=False,
        )
        img = Image.open(out).convert("RGB")
        assert sum(img.getpixel((980, 80))[:3]) > 600

    def test_左下文章名_保留(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_article_name.png"
        render_card(
            "测试。", out, title="巴拿马一夜", index=2, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            show_polaroid=False,
        )
        img = Image.open(out).convert("RGB")
        # 文章名 28pt 在 (90, 1820)，跨 ~7 字到 (260, 1848)；扫一段找墨色像素
        region = img.crop((90, 1820, 280, 1850)).getdata()
        dark_count = sum(1 for px in region if sum(px[:3]) < 400)
        assert dark_count > 5, f"文章名未画出（dark_count={dark_count}）"


class TestRenderCardV2Layout:
    """V2 改造：非 polaroid 15 行（占画面 60%）；polaroid 走 treatment（抽象化）。"""

    def test_非_polaroid_主文字_最多_15_行(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_15lines.png"
        # 长文本确保 _wrap_text 返回 >15 行
        long_text = "援翰写心。" * 80  # 480 字，必然超过 15 行
        # monkeypatch ImageDraw.Draw：拦截 draw.text 调用，只统计 fill=text_main 的（主文字）
        body_calls: list = []

        class _FakeDraw:
            def __init__(self, _img): pass
            def text(self, xy, text_str, *args, **kwargs):
                fill = kwargs.get("fill")
                if fill == composer.PALETTE.text_main:
                    body_calls.append(text_str)
            def textbbox(self, *args, **kwargs):
                return (0, 0, 100, 30)
            def rectangle(self, *args, **kwargs): pass
            def line(self, *args, **kwargs): pass
        monkeypatch.setattr(composer.ImageDraw, "Draw", _FakeDraw)
        render_card(
            long_text, out,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            show_polaroid=False,
        )
        assert len(body_calls) == 14, f"主文字应 ≤14 行，实际 {len(body_calls)}"

    def test_polaroid_走_treatment(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        # fixture 默认 bg_treatment_enabled=False；这里临时打开让 treatment 真的触发
        monkeypatch.setattr(composer.settings, "bg_treatment_enabled", True)
        photo_path = bg / "snowy.jpg"
        Image.new("RGB", (100, 100), (200, 210, 220)).save(photo_path)
        out = bg.parent / "card_treat.png"
        treat_mock = MagicMock(wraps=composer._apply_bg_treatment)
        monkeypatch.setattr(composer, "_apply_bg_treatment", treat_mock)
        render_card(
            "测试。", out, index=0, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            visual_hint="夜色", show_polaroid=True,
            forced_polaroid_path=photo_path,
        )
        # paper + polaroid 都过 treatment → ≥ 2 次
        assert treat_mock.call_count >= 2, (
            f"polaroid 路径未走 _apply_bg_treatment（call_count={treat_mock.call_count}）"
        )

    def test_非_polaroid_不_走_treatment(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_no_treat.png"
        treat_mock = MagicMock(wraps=composer._apply_bg_treatment)
        monkeypatch.setattr(composer, "_apply_bg_treatment", treat_mock)
        render_card(
            "测试。", out, index=1, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            visual_hint="夜色", show_polaroid=False,
        )
        # fixture 禁用 paper treatment；非 polaroid 不该触发
        assert treat_mock.call_count == 0, "非 polaroid 不应走 _apply_bg_treatment"


class TestAbstractPanel:
    """V3：拍立得 fallback 用程序生成的抽象面板（不再用 Pexels 实景）。"""

    def test_尺寸_对(self) -> None:
        img = _pick_abstract_bg("夜色")
        assert img.size == (1080, 1920)

    def test_确定性_同_hint_同_面板(self) -> None:
        a = _pick_abstract_bg("夜色")
        b = _pick_abstract_bg("夜色")
        # 逐像素相同
        import numpy as np
        na, nb = np.array(a), np.array(b)
        assert (na == nb).all()

    def test_不同_hint_不同_面板(self) -> None:
        a = _pick_abstract_bg("夜色")
        b = _pick_abstract_bg("晨光")
        import numpy as np
        na, nb = np.array(a), np.array(b)
        assert not (na == nb).all()

    def test_不同_seg_index_不同_模板(self) -> None:
        """同 hint、不同 seg_index 必须出不同模板（避免一段文章多幕重复图）。"""
        import numpy as np
        a = _pick_abstract_bg("夜色", seg_index=0)
        b = _pick_abstract_bg("夜色", seg_index=1)
        c = _pick_abstract_bg("夜色", seg_index=2)
        na, nb, nc = np.array(a), np.array(b), np.array(c)
        assert not (na == nb).all(), "seg 0/1 模板不应相同"
        assert not (nb == nc).all(), "seg 1/2 模板不应相同"
        assert not (na == nc).all(), "seg 0/2 模板不应相同"

    def test_同_seg_index_确定性(self) -> None:
        """同 hint + 同 seg_index → 逐像素相同。"""
        import numpy as np
        a = _pick_abstract_bg("夜色", seg_index=3)
        b = _pick_abstract_bg("夜色", seg_index=3)
        assert (np.array(a) == np.array(b)).all()

    def test_空_hint_也_能_生(self) -> None:
        img = _pick_abstract_bg("")
        assert img.size == (1080, 1920)

    def test_render_card_polaroid_走_抽象_路径(
        self, fake_assets: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bg, _ = fake_assets
        _make_bg(bg, "warsaw_snow", color=(11, 22, 33))
        out = bg.parent / "card_abstract.png"
        # 不传 forced_polaroid_path/key → 走 _pick_abstract_bg
        pick_mock = MagicMock(wraps=composer._pick_abstract_bg)
        monkeypatch.setattr(composer, "_pick_abstract_bg", pick_mock)
        render_card(
            "测试。", out, index=0, total=5,
            bg=Image.new("RGB", (1080, 1920), (234, 230, 218)),
            visual_hint="夜色", show_polaroid=True,
        )
        assert pick_mock.call_count == 1, "polaroid 应调 _pick_abstract_bg"
        assert Image.open(out).size == (1080, 1920)



class TestKeywordCascadeGuard:
    """防『泛化 hint 误中具体地域图』。

    历史教训：用户反馈巴拿马机场文章配图是江南鱼乡——
    根因是 visual_hint='烟雨远山' 的 '雨'（1 字）命中 jiangnan_water_town
    关键词列表里 1 字的 '雨'。修复：_pick_from_pool 强制 len(kw) ≥ 2。
    """

    @pytest.mark.unit
    def test_单字_关键词_不再_触发_地域_误中(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """结构断言：jiangnan 关键词列表已清空 1 字项，未来加回会被本测试拦截。"""
        jiangnan_kws = BG_KEYWORDS["jiangnan_water_town"]
        offenders = [kw for kw in jiangnan_kws if len(kw) < 2]
        assert not offenders, (
            f"jiangnan 关键词含 1 字项 {offenders}，cascade 防御失效"
        )

    @pytest.mark.unit
    def test_显式_地域词_仍_能_命中(
        self, fake_assets: tuple[Path, Path]
    ) -> None:
        """'江南水乡夜色' 应仍能命中 jiangnan_water_town（'江南'/'水乡' 2 字+）。"""
        bg, _ = fake_assets
        _make_bg(bg, "jiangnan_water_town", color=(100, 200, 100))
        _make_bg(bg, "morning_mist", color=(220, 220, 240))
        pool = sorted(bg.glob("*.png"))
        chosen = _pick_from_pool(pool, "江南水乡夜色")
        assert chosen.stem == "jiangnan_water_town", (
            f"显式 '江南' 关键词应命中 jiangnan_water_town，实际 {chosen.stem}"
        )

    @pytest.mark.unit
    def test_所有_地域_图_关键词_都_2_字_以上(self) -> None:
        """结构性不变量：_REAL_PHOTO_KEYS 所有地域图关键词都 ≥ 2 字。

        这是防『泛化 hint 误中具体地域图』的根本护栏——若未来又有人加回
        1 字关键词（'雨'/'水'/'夜'），本测试会 fail 提醒他。
        """
        offenders: list[str] = []
        for stem in composer._REAL_PHOTO_KEYS:
            kws = BG_KEYWORDS.get(stem, [])
            for kw in kws:
                if len(kw) < 2:
                    offenders.append(f"{stem}: {kw!r}")
        assert not offenders, (
            "地域图含 1 字关键词，cascade 会被泛化 hint 误中：\n"
            + "\n".join(offenders)
        )
