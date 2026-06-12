"""视频合成：水墨淡雅背景（按 visual_hint 匹配） + 字幕卡 + 配音 + 背景音乐。

Pipeline:
1) 用 PIL 为每段口播渲染一张 9:16 字幕卡（淡雅底色 + 竖排中文）
2) 每段按 LLM 给的 visual_hint 关键词，从 assets/backgrounds/ 挑一张最匹配的水墨图
3) ffmpeg zoompan 拼接为带 Ken Burns 动效的视频（每段缓慢放大 5%）
4) 加背景音乐（按 _pick_music 从 assets/music/ 随机挑）→ 最终 mp4
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.config import settings
from app.llm.base import ScriptSegment, VideoScript


# === 中文字体（macOS 自带） ===
_CANDIDATE_FONTS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Songti.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _find_chinese_font() -> str:
    for f in _CANDIDATE_FONTS:
        if Path(f).exists():
            return f
    raise RuntimeError("未找到可用的中文字体，请在 assets/fonts 下放置 .ttf/.ttc 后修改 _CANDIDATE_FONTS")


# === 调色板：淡雅、隽永 ===
@dataclass(frozen=True)
class Palette:
    bg_top: tuple[int, int, int] = (242, 236, 222)       # 米黄
    bg_bottom: tuple[int, int, int] = (228, 224, 210)     # 淡灰米
    text_main: tuple[int, int, int] = (62, 56, 50)        # 墨色
    text_sub: tuple[int, int, int] = (130, 120, 108)      # 淡墨
    accent: tuple[int, int, int] = (158, 122, 92)         # 淡赭（点缀）
    rule: tuple[int, int, int] = (190, 178, 158)          # 细线


PALETTE = Palette()


def _gradient_bg(w: int, h: int) -> Image.Image:
    """纯渐变背景（无外部图时的 fallback）。"""
    img = Image.new("RGB", (w, h), PALETTE.bg_top)
    top = PALETTE.bg_top
    bot = PALETTE.bg_bottom
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


# === 视觉意象 → 背景图关键词映射 ===
# visual_hint 是 LLM 给每段生成的 3-8 字意象（"墨竹轻摇"、"远山烟雨" 等），
# 合成器据此从 assets/backgrounds/ 里挑最匹配的水墨图。
# 命中多个关键词时取最长的（更具体）；都不命中则随机挑一张。
BG_KEYWORDS: dict[str, list[str]] = {
    "misty_mountains": ["山", "远山", "云", "雾", "山色", "翠微", "峰", "岭", "岱", "巍", "岚", "归鸟"],
    "rain_jiannan":    ["雨", "烟雨", "江南", "春雨", "梅雨", "湿", "滴", "淋漓", "雨巷"],
    "ink_bamboo":      ["竹", "墨竹", "清影", "清风", "节", "正直", "七贤", "风骨", "萧萧"],
    "lone_boat":       ["舟", "船", "渡", "渔", "江", "河", "水流", "潮", "岸", "夜泊"],
    "sunset_glow":     ["夕阳", "落日", "黄昏", "余晖", "红霞", "日落", "晚", "暮"],
    "snow_night":      ["雪", "冬", "夜", "灯", "孤灯", "寒", "白", "冰", "炉", "火"],
    "ancient_path":    ["古道", "西风", "瘦马", "路", "旅途", "远行", "征", "天涯"],
    "deep_courtyard":  ["庭院", "院", "深", "老屋", "宅", "家", "堂", "厅", "老宅"],
    "cup_of_tea":      ["茶", "茗", "杯", "盏", "清茶", "品茗", "香", "残茶"],
    "rain_plantain":   ["芭蕉", "雨打", "夏", "凉", "荫", "绿", "荫凉"],
    "desert_smoke":    ["沙漠", "大漠", "孤烟", "戈壁", "西北", "驼", "胡", "黄沙"],
    "rice_paper":      ["纸", "墨", "书", "信", "字", "卷", "古", "经", "诗", "题字", "书页", "月下书页"],
    # === 第二批（清新风景 + 静物 12 张，Pexels License 1080x1920） ===
    # 晨雾、湖面薄雾、清晨朦胧。避开原 misty_mountains 的"山/雾/云/远山"
    "morning_mist":   ["晨雾", "晓雾", "薄雾", "朝雾", "晨光", "晨曦", "破晓", "黎明", "晨曦微露", "水面雾", "拂晓"],
    # 青山新绿、春日嫩芽。避开原 misty_mountains 的"山/远山/翠微/峰/岭"
    "green_hills":    ["青山", "新绿", "嫩绿", "春山", "新芽", "嫩芽", "萌", "绿意", "春色", "青翠", "新枝", "抽芽"],
    # 静湖倒影、平湖如镜。避开原 lone_boat 的"舟/船/江/河/渡/渔"
    "quiet_lake":     ["静湖", "平湖", "湖面", "倒影", "湖水", "湖光", "湖色", "镜湖", "明湖", "湖平", "一潭"],
    # 林荫小径、雾林、晨光透林。避开原 ink_bamboo 的"竹/清影/清风"
    "forest_path":    ["林荫", "林间", "林路", "林深", "树影", "松林", "林梢", "林海", "密林", "晨林", "林间光"],
    # 野花田、草甸。避开"花"太宽泛（会让 rice_paper 等都命中），用复合词
    "flower_field":   ["野花", "花田", "花海", "草甸", "白花", "雏菊", "野菊", "满天星", "野花丛", "花野"],
    # 阳光透窗、暖光斜照。避开原 snow_night 的"灯"
    "sunlit_window":  ["透窗", "窗光", "窗影", "室内光", "斜阳", "斜照", "窗前光", "暖光", "一束光", "光影", "日影"],
    # 翻开的书页。避开原 rice_paper 的"书/字/卷/经/诗"
    "open_book":      ["翻书", "翻开", "书页", "书翻开", "书卷气", "翻页", "读本", "外文", "洋装书", "西书"],
    # 毛笔砚台、文房。避开原 ink_bamboo 的"墨竹/竹/清影"和 rice_paper 的"墨/经"
    "ink_brush":      ["毛笔", "笔架", "砚台", "砚", "笔洗", "笔筒", "文房", "笔搁", "笔帘", "宣笔", "湖笔"],
    # 窗台瓶花、晨光下静物。避开原 deep_courtyard 的"庭院/院/堂/厅"
    "window_sill":    ["窗台", "窗前", "瓶花", "案头花", "瓶中花", "插花", "案上花", "瓶插", "案清", "瓶供"],
    # 信纸钢笔手写信。避开原 rice_paper 的"纸/墨/书/信/字/卷"
    "paper_letter":   ["信纸", "信札", "手书", "钢笔字", "墨笔字", "钢笔", "钢笔信", "家书", "手写信", "便笺", "短笺"],
    # 青瓷/白瓷茶具。避开原 cup_of_tea 的"茶/茗/杯/盏/清茶/品茗"
    "ceramic_cup":    ["瓷杯", "瓷盏", "瓷壶", "青瓷", "白瓷", "瓷", "细瓷", "杯盏", "素瓷", "瓷碗", "器皿"],
    # 烛台暖光、夜读小灯。避开原 snow_night 的"灯/孤灯/夜"
    "candle_warm":    ["烛光", "烛", "烛台", "烛影", "烛火", "夜读", "灯下读", "夜灯", "烛照", "烛泪", "灯烛"],

    # === 第三批（地域写真 12 张，Wikipedia 公共域/CC 1080x1920） ===
    # cascade 走 location_tags 时，visual_hint 在地域子集内 longest-match 二选。
    # 关键词尽量与既有 key 不冲突，避免误命中。
    # 波兰 / 华沙
    "warsaw_old_town":       ["老城", "城堡", "广场", "街", "波兰", "华沙"],
    "warsaw_winter_street":  ["街", "建筑", "城", "暖", "华沙", "欧", "古"],
    "krakow_square":         ["广场", "老城", "市集", "钟楼"],
    "eastern_church":        ["教堂", "塔", "洋葱", "俄", "苏联", "古"],
    # 日本
    "kyoto_temple_street":   ["寺", "塔", "灯笼", "红", "和", "传统", "石阶"],
    "tokyo_alley":           ["巷", "霓虹", "灯", "夜", "都市"],
    # 中国 / 江南
    "jiangnan_water_town":   ["水", "船", "桥", "江南", "雨"],
    "china_old_town":        ["屋", "瓦", "巷", "古", "灯笼", "红", "毛皮", "羊皮"],
    "ancient_bridge":        ["桥", "水", "亭", "古桥"],
    # 西欧
    "paris_cafe":            ["咖啡", "巴黎", "街", "灯", "法"],
    "london_rain_street":    ["雨", "街", "雾", "伦敦", "英"],
    "rome_cobblestone_alley":["巷", "石", "古", "罗马"],
    # === 第四批：东欧冷寂系自然风景（原始森林/冷湖/松林/雾河/沼泽/运河）===
    # 视觉调：墨绿、冷、雾、暗——给波兰/苏联时期故事做"异国荒野"的 negative space
    "bialowieza_forest":   ["森林", "树", "林", "暗", "墨绿", "静", "雾", "针叶", "野", "原始", "苔"],
    "masurian_lake":       ["湖", "水", "雾", "晨", "冷", "静", "远", "冷湖", "平湖", "水面"],
    "tatra_mountain":      ["雪山", "雪夜", "山", "松", "雪", "峰", "高", "冷", "暗", "针叶", "塔特拉", "岭"],
    "augustow_canal":      ["运河", "水", "船", "静", "远", "河", "倒影"],
    "biebrza_marsh":       ["湿地", "沼泽", "草", "雾", "水", "冷", "静", "别布扎", "晨雾"],
    # === 第五批：东欧天气场景（雪/雨/雾/夜，每张体现"天气+城市"）===
    # 2 字天气词让雪/雾/夜主题 visual_hint 在 poland cascade 池里压过晴天图。
    "moscow_snow":        ["雪夜", "风雪", "寒夜", "漫天雪", "雪", "冬", "冰", "寒", "俄", "莫斯科", "运河", "冰封", "冻"],
    "warsaw_snow":        ["雪夜", "风雪", "寒夜", "漫天雪", "雪", "冬", "港", "岸", "华沙", "冰", "寒", "冷"],
    "krakow_rain":        ["雨巷", "雨", "湿", "巷", "石", "街", "灰", "克拉科夫"],
    "warsaw_fog":         ["雾晨", "薄雾", "晨雾", "雾", "晨", "朦胧", "华沙", "街", "灰", "迷"],
    "warsaw_night":       ["夜色", "夜灯", "夜晚", "夜", "灯", "光", "华沙", "街", "灯火", "暗"],
    "prague_snow":        ["雪夜", "风雪", "雪", "冬", "城", "布拉格", "古", "街", "寒", "老城"],
    "budapest_night":     ["夜色", "夜灯", "夜晚", "夜", "灯", "光", "布达佩斯", "桥", "河", "暗"],
}


# === 图像作用域分组 ===
# 真实摄影图（Pexels）——拍立得卡片里用，保持清晰、信息明确。
# 这里登记所有真实摄影 key（包括后续扩展的地域写真）；PNG 不存在时 glob 自动跳过。
_REAL_PHOTO_KEYS: frozenset[str] = frozenset({
    # 原 12 张通用（晨雾/绿山/茶杯/烛火 等）
    "morning_mist", "green_hills", "quiet_lake", "forest_path",
    "flower_field", "sunlit_window", "open_book", "ink_brush",
    "window_sill", "paper_letter", "ceramic_cup", "candle_warm",
    # 东欧 / 波兰
    "warsaw_old_town", "warsaw_winter_street", "krakow_square", "eastern_church",
    # 东欧冷寂系自然（第四批，5 张，墨绿/冷/雾/暗）
    "bialowieza_forest", "masurian_lake", "tatra_mountain",
    "augustow_canal", "biebrza_marsh",
    # 东欧天气场景（第五批，7 张，雪/雨/雾/夜/晴）
    "moscow_snow", "warsaw_snow", "krakow_rain",
    "warsaw_fog", "warsaw_night", "prague_snow", "budapest_night",
    # 日本
    "kyoto_temple_street", "tokyo_alley",
    # 中国 / 江南
    "jiangnan_water_town", "china_old_town", "ancient_bridge",
    # 西欧
    "paris_cafe", "london_rain_street", "rome_cobblestone_alley",
})
# 水墨占位图（PIL 生成的抽象面板）——纸面背景用，走 heavy treatment 退成氛围底
_INK_BG_KEYS: frozenset[str] = frozenset({
    "misty_mountains", "rain_jiannan", "ink_bamboo", "lone_boat",
    "sunset_glow", "snow_night", "ancient_path", "deep_courtyard",
    "cup_of_tea", "rain_plantain", "desert_smoke", "rice_paper",
})


# === manifest.json 加载 ===
# 每张真实摄影图的"名片"：location / era / scene / caption_hint。
# 缺失/损坏 → 返回 {}（走 generic fallback，不报错）。
from functools import lru_cache
import json
import logging

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_manifest() -> dict[str, dict]:
    """manifest 一次性加载。缺失或损坏 → 返回空 dict。"""
    p = settings.asset_bg_dir / "manifest.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        # 过滤掉 _doc / _fallback_universal 之类非图片条目
        return {
            k: v for k, v in data.items()
            if not k.startswith("_") and isinstance(v, dict)
        }
    except Exception:
        logger.warning("manifest.json 解析失败，走 generic fallback", exc_info=True)
        return {}


def _pick_from_pool(pool: list[Path], visual_hint: str) -> Path:
    """既有 longest-match 关键词匹配 + random 兜底；抽出来便于 cascade 复用。"""
    hint = visual_hint or ""
    best: Path | None = None
    best_len = 0
    for filename, keywords in BG_KEYWORDS.items():
        for kw in keywords:
            if kw in hint and len(kw) > best_len:
                cand_path = next((p for p in pool if p.stem == filename), None)
                if cand_path is not None:
                    best = cand_path
                    best_len = len(kw)
    return best if best is not None else random.choice(pool)


def _open_and_maybe_treat(path: Path, treat: bool) -> Image.Image | None:
    """读 PNG → 必要时 resize → 必要时走 treatment。失败返回 None。"""
    try:
        img = Image.open(path).convert("RGB")
        if img.size != (settings.video_width, settings.video_height):
            img = img.resize(
                (settings.video_width, settings.video_height), Image.LANCZOS
            )
        if treat and settings.bg_treatment_enabled:
            img = _apply_bg_treatment(img)
        return img
    except Exception:  # noqa: BLE001
        return None


def _pick_background(
    visual_hint: str,
    *,
    treat: bool = True,
    scope: str = "all",
    article_context: dict | None = None,
) -> Image.Image | None:
    """根据 visual_hint 关键词挑最匹配的水墨背景图。

    命中多个时取关键词最长的（更具体）；都不命中则随机挑一张。
    返回 None 让上层回退到纯渐变。

    treat=False 时跳过 `_apply_bg_treatment`——拍立得里那张图要保持清晰，
    不被氛围蒙版压平（与 BG 退成氛围底相反）。

    scope 限定候选池：
      - "all"（默认）：所有图都可选
      - "real"：只在真实摄影图里挑（拍立得卡片用）
      - "ink" ：只在水墨占位图里挑（纸面背景用）

    article_context（可选）：文章级地域 context，cascade 优先于 visual_hint——
      - None 或 {"location_tags": []} → 现有 generic 行为（视觉提示关键词匹配）
      - {"location_tags": ["poland"]} → 先按地域筛 manifest 命中的子集，
        再在子集内按 visual_hint 选；保证"波兰故事 → 波兰图"。

    cascade 设计：地域匹配是"硬约束"（波兰故事不会随机到日本图），
    visual_hint 是"软二选"（同是波兰图，挑更贴本段意象的那张）。
    """
    bg_dir = settings.asset_bg_dir
    if not bg_dir.exists():
        return None
    if scope == "real":
        allowed = _REAL_PHOTO_KEYS
    elif scope == "ink":
        allowed = _INK_BG_KEYS
    else:
        allowed = None  # 不过滤
    pool = sorted(
        p for p in bg_dir.glob("*.png")
        if allowed is None or p.stem in allowed
    )
    if not pool:
        return None

    # === Cascade：地域优先（仅 scope=real 且 context 非空时启用）===
    if scope == "real" and article_context:
        tags = article_context.get("location_tags") or []
        if tags:
            manifest = _load_manifest()
            tagset = set(tags)
            regional = [
                p for p in pool
                if p.stem in manifest
                and set(manifest[p.stem].get("location", [])) & tagset
            ]
            if regional:
                # 地域匹配子集内仍走 visual_hint longest-match
                chosen = _pick_from_pool(regional, visual_hint)
                return _open_and_maybe_treat(chosen, treat)
            # 子集空（manifest 没匹配项或地域未登记）→ fallback 到 generic
            logger.debug(
                "[pick_bg] location_tags=%s 无匹配照片，fallback 到 generic",
                tags,
            )

    # === 既有 generic 路径（视觉提示关键词 + 随机兜底）===
    chosen = _pick_from_pool(pool, visual_hint)
    return _open_and_maybe_treat(chosen, treat)


# === 背景图氛围处理（让真摄影图退一步，跟字共处） ===

# 蒙版透明度：0=原图不变，1=纯米色看不到图。0.38 = 退一步不抢字（v1 0.55 过重把高光压平了）
_BG_MASK_ALPHA = 0.38
# 高斯模糊半径：让焦点变软，眼睛自然落到字上。0=不模糊；2-3 = 似看见非看见
_BG_BLUR_RADIUS = 2.5
# 饱和度系数：1=原色，0=灰。0.65 = 还能辨色但不喧宾夺主
_BG_SATURATION = 0.65
# Vignette 强度：0=无暗角，1=四周全米色。0.22 = 中央隐约成阅读区（v1 0.35 太黑）
_BG_VIGNETTE_STRENGTH = 0.22


def _vignette_mask(w: int, h: int, strength: float) -> Image.Image:
    """生成径向 alpha 蒙版：中央透明、四周不透明。"""
    # 椭圆 mask：先画白底（不透明）+ 中央黑椭圆（透明），再大模糊柔化边缘
    m = Image.new("L", (w, h), int(255 * strength))
    d = ImageDraw.Draw(m)
    # 中央椭圆覆盖 80% 区域，画 0 表示这里不要 vignette
    pad_x, pad_y = int(w * 0.10), int(h * 0.10)
    d.ellipse((pad_x, pad_y, w - pad_x, h - pad_y), fill=0)
    # 大模糊把硬边缘变成柔渐变
    m = m.filter(ImageFilter.GaussianBlur(radius=min(w, h) // 6))
    return m


def _apply_bg_treatment(img: Image.Image) -> Image.Image:
    """图预处理三件套 + 暗角：让真摄影图变成"染纸黄的氛围底"。

    1) 高斯模糊（焦点变软）
    2) 降饱和（色彩克制）
    3) 米色蒙版（统一调到 PALETTE.bg_top 纸黄）
    4) Vignette（中央透明、四周米色 → 中心天然阅读区）

    水墨占位图本来就低饱和、淡米调，再处理基本无副作用；真摄影图收益最大。
    """
    # 1) blur
    if _BG_BLUR_RADIUS > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=_BG_BLUR_RADIUS))
    # 2) saturation
    if _BG_SATURATION < 1.0:
        img = ImageEnhance.Color(img).enhance(_BG_SATURATION)
    # 3) 米色蒙版（PALETTE.bg_top 同色）
    if _BG_MASK_ALPHA > 0:
        overlay = Image.new("RGB", img.size, PALETTE.bg_top)
        img = Image.blend(img, overlay, _BG_MASK_ALPHA)
    # 4) Vignette（四周再向米色靠拢）
    if _BG_VIGNETTE_STRENGTH > 0:
        w, h = img.size
        mask = _vignette_mask(w, h, _BG_VIGNETTE_STRENGTH)
        vignette_color = Image.new("RGB", (w, h), PALETTE.bg_top)
        img = Image.composite(vignette_color, img, mask)
    return img


def _split_oversize(tk: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """超宽 token 按字符切成多段，每段都 ≤ max_width。"""
    chunks: list[str] = []
    cur = ""
    for ch in tk:
        nxt = cur + ch
        if font.getlength(nxt) <= max_width:
            cur = nxt
        else:
            if cur:
                chunks.append(cur)
            cur = ch
    if cur:
        chunks.append(cur)
    return chunks


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度换行，保护数字 / 英文 / 时间戳不被拆，标点附在行尾。"""
    import re

    text = text.strip()
    # 标点集合：附在前一 token 后面
    PUNCT_TAIL = set("。！？!?；;,，.、")
    # 破折号 / 省略号：附在 token 中或后都行
    DASH = set("—-…～~")
    # 1) 按标点先切（保留标点）
    parts = re.findall(r"[^。！？!?；;，,\.]{1,40}[。！？!?；;，,\.]?", text)
    if not parts:
        parts = [text]
    lines: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if font.getlength(p) <= max_width:
            lines.append(p)
            continue
        # 2) 长段按 token 切
        # token: 连续中文字 / 连续数字+英文 / 单个标点
        tokens = re.findall(r"[一-鿿]+|[0-9A-Za-z:：/\-]+|[一-鿿0-9A-Za-z]|[^一-鿿0-9A-Za-z]", p)
        buf = ""
        for tk in tokens:
            if tk in PUNCT_TAIL or tk in DASH:
                # 标点和破折号附在 buf 后面（如果 buf 非空）
                if buf:
                    cand = buf + tk
                    if font.getlength(cand) <= max_width:
                        buf = cand
                    else:
                        lines.append(buf.rstrip())
                        # 标点放不下单独一行的下一行
                        buf = tk if font.getlength(tk) <= max_width else ""
                else:
                    # buf 空，标点不要单独成行 → 加到下一行
                    buf = tk
                continue
            cand = buf + tk
            if font.getlength(cand) <= max_width:
                buf = cand
            else:
                if buf:
                    lines.append(buf.rstrip())
                    buf = ""
                # 单 token 比 max_width 还宽：按字符切
                if font.getlength(tk) > max_width:
                    chunks = _split_oversize(tk, font, max_width)
                    # 前 N-1 段直接成行，最后一段进 buf 继续累加
                    for c in chunks[:-1]:
                        lines.append(c)
                    buf = chunks[-1] if chunks else ""
                else:
                    buf = tk
        if buf:
            lines.append(buf.rstrip())
    # 后处理：合并行首孤立的标点 / 破折号到上一行（仅当合并后仍不超宽时）
    merged: list[str] = []
    for ln in lines:
        if (
            merged
            and ln
            and (ln[0] in PUNCT_TAIL or ln[0] in DASH)
            and font.getlength(merged[-1] + ln) <= max_width
        ):
            merged[-1] = merged[-1] + ln
        else:
            merged.append(ln)
    return merged


# === Polaroid 拍立得卡（杂志卡片式排版） ===

# 拍立得卡片尺寸：宽 720 / 高 720
_POLAROID_W = 720
_POLAROID_H = 720
# 卡片内图区：4:3，640x480
_POLAROID_IMG_W = 640
_POLAROID_IMG_H = 480
_POLAROID_PAD_X = (_POLAROID_W - _POLAROID_IMG_W) // 2  # 40
_POLAROID_PAD_TOP = 40
# 卡片底色：暖白
_POLAROID_CARD_BG = (252, 248, 240)


def _crop_aspect(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """中心裁切到目标宽高比，再 resize。"""
    sw, sh = img.size
    src_ar = sw / sh
    dst_ar = target_w / target_h
    if src_ar > dst_ar:
        # 原图更宽 → 裁左右
        new_sw = int(sh * dst_ar)
        x0 = (sw - new_sw) // 2
        img = img.crop((x0, 0, x0 + new_sw, sh))
    else:
        # 原图更高 → 裁上下
        new_sh = int(sw / dst_ar)
        y0 = (sh - new_sh) // 2
        img = img.crop((0, y0, sw, y0 + new_sh))
    return img.resize((target_w, target_h), Image.LANCZOS)


def _render_polaroid_card(
    image: Image.Image,
    caption: str,
) -> tuple[Image.Image, Image.Image]:
    """返回 (card, shadow) — 拍立得白卡 + 4:3 图 + caption + 极轻投影。

    card: 720x720 RGB 暖白卡
    shadow: 736x736 RGBA 模糊阴影（偏移 8,8），由 caller 合成
    """
    card = Image.new("RGB", (_POLAROID_W, _POLAROID_H), _POLAROID_CARD_BG)
    cropped = _crop_aspect(image, _POLAROID_IMG_W, _POLAROID_IMG_H)
    card.paste(cropped, (_POLAROID_PAD_X, _POLAROID_PAD_TOP))

    # caption（卡片下半部分，居中）
    font_cap = ImageFont.truetype(_find_chinese_font(), 26)
    draw = ImageDraw.Draw(card)
    bbox = draw.textbbox((0, 0), caption, font=font_cap)
    cw = bbox[2] - bbox[0]
    draw.text(
        ((_POLAROID_W - cw) / 2, _POLAROID_PAD_TOP + _POLAROID_IMG_H + 50),
        caption, font=font_cap, fill=PALETTE.text_sub,
    )

    # 极轻投影：偏移 8,8，模糊 6，alpha 38/255（让卡浮起来）
    shadow = Image.new(
        "RGBA", (_POLAROID_W + 16, _POLAROID_H + 16), (0, 0, 0, 0)
    )
    sd2 = ImageDraw.Draw(shadow)
    sd2.rectangle(
        [(8, 8), (_POLAROID_W + 8, _POLAROID_H + 8)],
        fill=(0, 0, 0, 38),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
    return card, shadow


def _short_caption_from(text: str, max_chars: int = 6) -> str:
    """从正文抽 2-max_chars 个非标点字做 caption。"""
    cleaned = "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return cleaned[:max_chars]


def render_card(
    text: str,
    out_path: Path,
    *,
    title: str = "",
    subtitle: str = "",
    index: int = 0,
    total: int = 0,
    bg: Image.Image | None = None,
    closing: bool = False,
    visual_hint: str = "",
    caption: str = "",
    article_context: dict | None = None,
    forced_polaroid_key: str | None = None,
    forced_polaroid_path: Path | None = None,
) -> Path:
    """渲染一张字幕卡。bg 为 None 时用纯渐变。

    closing=True：去除所有装饰（顶/底规则线、脚注、进度），用纯渐变背景，
    加大字号，让 closing 文字成为画面唯一主体。

    非 closing：Polaroid 拍立得式排版——
      顶：页眉「援翰写心 · 卷」 + 进度
      中：720x720 白卡（含 4:3 居中图 + caption + 极轻投影）
      下：主文字（42pt 居中，最多 13 行；42pt × 17 字/行 ≈ 容纳 220 字，
         覆盖典型 100-200 字段落；末行 y≈1728 离页码 92px，不挤）
      底：朱红页码

    visual_hint：caller（compose_script）传入的 LLM 视觉提示词，
      用于挑拍立得里的图（BG 已由 caller 挑好，作为 paper 背景）。
    caption：caller 显式给定时优先（通常是 seg.visual_hint），否则从 text 抽 2-6 字。
    article_context：文章级地域 context（可选）。透传给 polaroid 的 _pick_background
      做 cascade 地域优先匹配；None 时走 generic 视觉提示路径。
    forced_polaroid_key：LLM 语义选图结果（可选）。非空时直接 load 对应 PNG，
      跳过 _pick_background 的 keyword cascade；None 时走原有选图路径。
    forced_polaroid_path：Pexels 搜图结果（任意本地文件，可选）。优先级最高。
      非空且文件存在时直接 load；否则退到 forced_polaroid_key；再否则走 _pick_background。
    """
    w, h = settings.video_width, settings.video_height

    font_path = _find_chinese_font()
    font_main = ImageFont.truetype(font_path, 42)
    font_meta = ImageFont.truetype(font_path, 30)
    font_closing = ImageFont.truetype(font_path, 76)

    if closing:
        # 极简版：纯渐变 + 居中加大文字 + 右下角一个小朱印
        img = bg.copy() if bg is not None else _gradient_bg(w, h)
        draw = ImageDraw.Draw(img)
        lines = _wrap_text(text, font_closing, w - 240)
        line_h = 120
        total_h = len(lines) * line_h
        start_y = (h - total_h) / 2
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font_closing)
            lw = bbox[2] - bbox[0]
            draw.text(
                ((w - lw) / 2, start_y + i * line_h),
                line, font=font_closing, fill=PALETTE.text_main,
            )
        # 小朱印：右下角 70x70，淡赭色（与 polaroid 印章同一母题）
        seal_x, seal_y = w - 200, h - 280
        draw.rectangle(
            [(seal_x, seal_y), (seal_x + 70, seal_y + 70)],
            fill=(180, 90, 70, 200),
        )
        if title:
            font_title = ImageFont.truetype(font_path, 28)
            draw.text((90, h - 100), f"《{title}》", font=font_title, fill=PALETTE.text_sub)
    else:
        # === Polaroid 拍立得式排版 ===
        # 1) 纸面：caller 提供的 BG 走 heavy treatment 退成氛围底
        paper = bg.copy() if bg is not None else _gradient_bg(w, h)
        if settings.bg_treatment_enabled:
            paper = _apply_bg_treatment(paper)
        canvas = paper.convert("RGBA")

        # 2) 拍立得里的图：关 treatment 直出（保留清晰）
        # 优先级：forced_polaroid_path（Pexels 搜图） > forced_polaroid_key（LLM 图库选图）> _pick_background
        if forced_polaroid_path and forced_polaroid_path.exists():
            polaroid_img = _open_and_maybe_treat(forced_polaroid_path, treat=False)
        elif forced_polaroid_key:
            photo_path = settings.asset_bg_dir / f"{forced_polaroid_key}.png"
            polaroid_img = _open_and_maybe_treat(photo_path, treat=False) if photo_path.exists() else None
        else:
            polaroid_img = _pick_background(
                visual_hint, treat=False, scope="real",
                article_context=article_context,
            )
        if polaroid_img is None:
            # 没图就 fallback 到纯米色填充
            polaroid_img = Image.new("RGB", (w, h), _POLAROID_CARD_BG)
        cap_text = caption or _short_caption_from(text) or visual_hint or "援翰写心"
        card, shadow = _render_polaroid_card(polaroid_img, cap_text)

        # 3) 把卡（含阴影）贴到纸面中央偏上
        card_x = (w - _POLAROID_W) // 2
        card_y = 200  # 顶 200px 留给页眉
        canvas.paste(shadow, (card_x - 8, card_y - 4), shadow)
        card_rgba = card.convert("RGBA")
        canvas.paste(card_rgba, (card_x, card_y), card_rgba)

        draw = ImageDraw.Draw(canvas)
        progress = f"{index + 1:02d} / {total:02d}" if total else ""

        # 4) 顶：页眉
        draw.text((90, 60), "援翰写心 · 卷", font=font_meta, fill=PALETTE.text_sub)
        if progress:
            bbox = draw.textbbox((0, 0), progress, font=font_meta)
            pw = bbox[2] - bbox[0]
            draw.text((w - 90 - pw, 60), progress, font=font_meta, fill=PALETTE.text_sub)

        # 5) 下：主文字（从 y=1000 开始，居中 720 宽，最多 13 行；
        #    42pt × 17 字/行 ≈ 220 字，覆盖典型 100-200 字段落；
        #    末行 y≈1728 离底页码 (y=1820) 还有 92px 间距）
        max_text_w = 720
        text_lines = _wrap_text(text, font_main, max_text_w)
        line_h = 56
        text_y = 1000
        for i, line in enumerate(text_lines[:13]):
            bbox = draw.textbbox((0, 0), line, font=font_main)
            lw = bbox[2] - bbox[0]
            draw.text(
                ((w - lw) / 2, text_y + i * line_h),
                line, font=font_main, fill=PALETTE.text_main,
            )

        # 6) 底：朱红页码（右下）+ 文章名（左下）
        if progress:
            page_y = h - 100
            bbox = draw.textbbox((0, 0), progress, font=font_meta)
            pw = bbox[2] - bbox[0]
            draw.text(
                (w - 90 - pw, page_y), progress, font=font_meta, fill=(180, 90, 70)
            )
        if title:
            font_title = ImageFont.truetype(font_path, 28)
            draw.text((90, h - 100), f"《{title}》", font=font_title, fill=PALETTE.text_sub)

        img = canvas.convert("RGB")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


# === 合成流水线 ===

# BGM 风格 → 关键词。BGM 文件名作为 key；每个 BGM 关联一组意象/情绪/地域/季节词。
# 用正文里的关键词打分挑最匹配的 BGM；不命中时 fallback 到随机。
BGM_MOOD: dict[str, list[str]] = {
    # 古琴：古风 / 山水 / 书卷 / 禅意 / 中式古典
    "ancient_guqin": [
        "古", "山", "墨", "书", "寺", "禅", "秦", "汉", "魏晋", "唐", "宋",
        "山水", "道", "隐", "山林", "竹", "松", "云", "水墨", "古风", "古典",
        "山色", "翠微", "岱", "巍", "岚", "高僧", "经", "诗", "卷", "题字",
    ],
    # 笛 / 箫：天涯 / 江湖 / 送别 / 边塞 / 侠义
    "flute_distant": [
        "笛", "箫", "天涯", "古道", "西风", "瘦马", "江湖", "侠", "远行", "旅途",
        "关山", "塞", "边", "故人", "送别", "送", "征", "客", "孤烟", "驼",
    ],
    # 极简钢琴：现代 / 城市 / 欧美 / 冬雪 / 记忆 / 人生 / 离别
    "piano_minimal": [
        "钢琴", "城市", "美国", "欧洲", "波兰", "法国", "德国", "英国", "俄国",
        "雪", "冬", "寒", "夜", "火车", "站", "离别", "重逢", "回忆", "童年",
        "老", "父", "母", "家", "病", "逝", "老去", "远方", "异国", "机场",
        "他乡", "重洋", "漂", "八十年代", "九十年代", "出生", "去世", "离世",
        "外", "外国", "洋", "北京", "上海", "丹佛", "波士顿", "柏林", "莫斯科",
        "华沙", "法兰克福", "科隆", "亚琛",
    ],
    # 氛围 pad：梦 / 空灵 / 静 / 深度 / 宇宙
    "ambient_pad": [
        "梦", "星辰", "宇宙", "未来", "空", "灵", "静", "冥想", "深", "远",
        "光", "影", "心", "魂", "灵性", "无", "广", "恒",
    ],
    # 雨声：雨 / 江南 / 芭蕉 / 春夏 / 水乡
    "rain_white_noise": [
        "雨", "湿", "梅雨", "芭蕉", "春", "夏", "江南", "水乡", "荷", "蝉",
        "烟雨", "漓", "滴", "淋漓", "湿漉",
    ],
    # === 第二批（incompetech.com CC BY 4.0，6 段新风格 BGM） ===
    # 温暖民谣：acoustic guitar + bass + brushed kit，somber / calming
    # 适配"民国家族、父亲、独白、故人、家常、乡下、老屋、童年、街巷、归乡"
    "warm_folk": [
        "民", "谣", "木屋", "家", "老屋", "旧居", "父", "母", "童年", "少年",
        "故里", "归乡", "回家", "回家路", "老友", "旧友", "老街", "巷", "柴门",
        "厨房", "灶", "柴", "炊烟", "乡下", "小镇", "邻家",
    ],
    # 古典吉他（nylon）+ 竖琴 + 长笛：Bright / Calm / Relaxed
    # 适配"清晨、晨光、湖边、花园、田园、明信片、少女、书桌、明媚、初春"
    "nylon_guitar": [
        "晨", "清", "晨光", "晨曦", "朝阳", "清晨", "明", "明媚", "晴", "天晴",
        "春", "初春", "早春", "春日", "春天", "花", "花园", "草坪", "野餐", "果",
        "果实", "摘", "轻", "轻盈", "雀跃", "笑意", "微笑", "少年", "少女", "风铃",
    ],
    # 大提琴 + 吉他 + 双簧管：Bright / Calm / Relaxed，古典向晚
    # 适配"告别、远行、车站、码头、留别、相送、离愁、晚年、人生、暮年、归途"
    "strings_emotional": [
        "告别", "送别", "送", "相送", "挥手", "挥别", "站台", "码头", "船", "启程",
        "远行", "行", "离", "别", "离愁", "愁", "老去", "暮年", "晚年", "人生",
        "回忆", "回望", "回首", "追忆", "终", "终章", "尾声", "末", "尽头", "落幕",
    ],
    # 手碟（tongue drum）+ 弦乐：Bright / Relaxed / Calming（28min 冥想型）
    # 适配"冥想、禅、入定、内观、空、山间、远山、独坐、心境、晨钟暮鼓"
    "handpan_calm": [
        "禅", "冥", "定", "入定", "内观", "静坐", "独坐", "空", "无", "虚",
        "心", "心境", "禅意", "禅房", "山寺", "古寺", "深山", "远山", "晨钟", "暮鼓",
        "梵", "修行", "清修", "觉悟", "寂", "静", "静谧", "宁", "安宁", "归宁",
    ],
    # 钢琴 + 弦乐：Calming / Mystical / Somber
    # 适配"电影感、宏大、年代、家族、近代、变迁、世纪、沉浮、人生回望、世纪之交"
    "piano_strings": [
        "电影", "片", "片头", "片尾", "序幕", "终幕", "章", "回", "世纪初", "世纪末",
        "近代", "民国", "现代", "当代", "变迁", "沉浮", "兴衰", "家族", "家史", "世纪",
        "宏", "宏大", "壮阔", "深沉", "厚重", "年代", "光阴", "流年", "岁", "年月",
    ],
    # 竖琴 + 长笛 + 合唱 + Helicons：Calming / Mystical / Uplifting
    # 适配"希望、黎明、新生、诞、破晓、星、光、梦、童话、童话般、童话里"
    "harp_dreamy": [
        "希望", "期", "盼", "盼头", "新生", "新", "破晓", "曙光", "黎", "晨光",
        "光", "光明", "星", "星辰", "星辉", "星夜", "梦", "梦境", "童话", "幻",
        "幻境", "升", "升腾", "飞扬", "飞", "飞升", "童", "童年", "童谣", "摇篮",
    ],
}


def _pick_music(music_dir: Path) -> Path | None:
    if not music_dir.exists():
        return None
    candidates = (
        sorted(music_dir.glob("*.mp3"))
        + sorted(music_dir.glob("*.wav"))
        + sorted(music_dir.glob("*.m4a"))
    )
    if not candidates:
        return None
    # 随机挑一首；空池时 fallback 到首项（几乎不会触发，防御性写法）
    return random.choice(candidates) if len(candidates) > 1 else candidates[0]


def _pick_music_for_body(body: str, music_dir: Path) -> Path | None:
    """根据正文关键词打分挑最匹配的 BGM。

    打分：每个 BGM 文件命中 BGM_MOOD 关键词的次数。
    最高分有多个时随机挑一个；无任何命中则 random.choice 兜底。
    """
    candidates = _list_music(music_dir)
    if not candidates:
        return None
    if not body:
        return random.choice(candidates) if len(candidates) > 1 else candidates[0]

    body = body or ""
    scored: list[tuple[int, Path]] = []
    for music_path in candidates:
        stem = music_path.stem
        kws = BGM_MOOD.get(stem, [])
        score = sum(1 for kw in kws if kw in body)
        scored.append((score, music_path))
    scored.sort(key=lambda x: -x[0])
    top_score, top_path = scored[0]
    if top_score == 0:
        # 没命中任何关键词 → 随机兜底
        return random.choice(candidates) if len(candidates) > 1 else candidates[0]
    # 取所有最高分候选随机挑
    top_paths = [p for s, p in scored if s == top_score]
    return random.choice(top_paths) if len(top_paths) > 1 else top_paths[0]


def _list_music(music_dir: Path) -> list[Path]:
    if not music_dir.exists():
        return []
    return (
        sorted(music_dir.glob("*.mp3"))
        + sorted(music_dir.glob("*.wav"))
        + sorted(music_dir.glob("*.m4a"))
    )


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    )
    return float(json.loads(out)["format"]["duration"])


def compose_script(
    script: VideoScript,
    work_dir: Path,
    output_path: Path,
    *,
    body: str = "",
    article_context: dict | None = None,
    llm_picks: dict[str, str | None] | None = None,
    photo_paths: dict[str, tuple[Path, dict] | None] | None = None,
) -> Path:
    """把脚本合成成视频。

    body：可选的原文章正文。传了就用 `_pick_music_for_body` 按关键词打分挑 BGM；
    不传（或空串）就退到 `_pick_music` 随机挑。背景图与 BGM 之外的逻辑不受影响。

    article_context：可选的文章级地域 context（来自 `extract_article_context`）。
    透传给每段 render_card → polaroid 的 _pick_background 做 cascade 地域优先。
    None 时走 generic 视觉提示路径。

    llm_picks：可选的 LLM 语义选图结果，key 为 visual_hint，value 为 photo_key 或 None。
    None 时 polaroid 走原有 _pick_background(keyword cascade)；传了则优先用 LLM 选的图。

    photo_paths：可选的 Pexels 搜图结果，key 为 visual_hint，value 为 (Path, photo_meta) 或 None。
    优先级最高。传了则直接 load 该 Path；否则退到 llm_picks；再否则走 _pick_background。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 0) 先为每段单独合成 TTS，得到每段真实时长
    from app.tts.edge import synth_segment

    seg_audios: list[Path] = []
    seg_durations: list[float] = []
    for i, seg in enumerate(script.segments):
        a = work_dir / f"seg_{i:02d}.mp3"
        d = synth_segment(seg.text, a)
        seg_audios.append(a)
        seg_durations.append(d)

    # 0.5) closing 也在这一步合成（拿到时长），这样 silent.mp4 能匹配 voice.mp3 长度
    if script.closing:
        closing_mp3 = work_dir / "closing.mp3"
        closing_dur = synth_segment(script.closing, closing_mp3)
        seg_audios.append(closing_mp3)
        seg_durations.append(closing_dur)

    # 给最后加一小段尾静音，避免太赶
    pad_after_last = 0.8
    seg_durations[-1] = seg_durations[-1] + pad_after_last

    # 1) 渲染每段字幕卡（按 visual_hint 关键词挑最匹配的水墨背景）
    total_cards = len(script.segments) + (1 if script.closing else 0)
    cards: list[Path] = []
    picks = llm_picks or {}
    paths = photo_paths or {}
    for i, seg in enumerate(script.segments):
        card_path = work_dir / f"card_{i:02d}.png"
        bg = _pick_background(seg.visual_hint, scope="ink")
        pexels_result = paths.get(seg.visual_hint)
        forced_path = pexels_result[0] if pexels_result else None
        render_card(
            seg.text,
            card_path,
            title=script.title,
            subtitle=script.subtitle,
            index=i,
            total=total_cards,
            bg=bg,
            visual_hint=seg.visual_hint,
            caption=seg.visual_hint,  # polaroid 卡的 caption 用 visual_hint（最贴意象）
            article_context=article_context,
            forced_polaroid_key=picks.get(seg.visual_hint),
            forced_polaroid_path=forced_path,
        )
        cards.append(card_path)

    # closing 字幕卡：极简版，纯渐变 + 居中加大文字 + 小朱印
    if script.closing:
        closing_card = work_dir / "card_closing.png"
        render_card(
            script.closing,
            closing_card,
            title=script.title,
            subtitle="",
            index=len(script.segments),
            total=total_cards,
            bg=None,  # 用纯渐变，避免 rice_paper 的横向虚线穿过文字
            closing=True,
        )
        cards.append(closing_card)

    # 2) 用真实时长拼字幕卡成视频（每段可选用 zoompan 做缓慢 Ken Burns 5% 缩放，再 concat）
    silent_video = work_dir / "silent.mp4"
    n = len(cards)
    w, h = settings.video_width, settings.video_height
    fps = 30
    cmd: list[str] = ["ffmpeg", "-y"]
    for c, d in zip(cards, seg_durations):
        cmd += ["-loop", "1", "-t", f"{d:.3f}", "-i", str(c)]
    # filter chain: Ken Burns 模式下每段用 zoompan；静态模式下直接 yuv420p
    if settings.video_ken_burns:
        chain = "".join(
            f"[{i}:v]fps={fps},"
            f"zoompan=z='1.0+0.05*on/{int(fps*d)}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={int(fps*d)}:s={w}x{h}:fps={fps},"
            f"format=yuv420p,setpts=PTS-STARTPTS[v{i}];"
            for i, d in enumerate(seg_durations)
        )
    else:
        # 静态：把每张图拉成对应时长（25fps，ffmpeg 图输入默认）
        chain = "".join(
            f"[{i}:v]format=yuv420p,setpts=PTS-STARTPTS[v{i}];"
            for i in range(n)
        )
    chain += "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    cmd += [
        "-filter_complex", chain,
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        str(silent_video),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        # 把 stderr 抛上来方便排查；正常路径不会到这
        sys.stderr.write(e.stderr)
        raise

    # 3) 配音：把每段音频按真实时长拼接成一条连续 voice.mp3（用 filter 重新编码，更稳）
    def _concat_audio(inputs: list[Path], out: Path) -> None:
        cmd = ["ffmpeg", "-y"]
        for a in inputs:
            cmd += ["-i", str(a)]
        chain = "".join(f"[{i}:a]aresample=44100,asetpts=PTS-STARTPTS[a{i}];" for i in range(len(inputs)))
        chain += "".join(f"[a{i}]" for i in range(len(inputs))) + f"concat=n={len(inputs)}:v=0:a=1[aout]"
        cmd += ["-filter_complex", chain, "-map", "[aout]", "-c:a", "libmp3lame", "-q:a", "5", str(out)]
        subprocess.run(cmd, check=True, capture_output=True)

    voice_mp3 = work_dir / "voice.mp3"
    # closing 已在步骤 0.5 合成并加进 seg_audios，这里直接 concat 全部
    _concat_audio(seg_audios, voice_mp3)

    # 4) 加背景音乐（如果有）
    # 4) 配 BGM：有 body 就按内容关键词打分；否则随机
    music = (
        _pick_music_for_body(body, settings.asset_music_dir)
        if body
        else _pick_music(settings.asset_music_dir)
    )
    if music:
        # BGM loop 到与视频等长。淡入 4s（用户要求渐入），淡出 3s。
        # 音量 0.90：BGM 源 -24dB → 归一 -24dB → 混音后 ~-26dB（人声 -20dB，BGM 只低 ~6dB，可闻）。
        voice_dur = _ffprobe_duration(voice_mp3)
        music_norm = work_dir / "music_norm.mp3"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-stream_loop", "-1",      # BGM 不足 60s 时循环填满
                "-i", str(music),
                "-t", str(voice_dur),
                "-af", "volume=0.90,afade=t=in:st=0:d=4,afade=t=out:st=" + str(max(voice_dur - 3, 0)) + ":d=3",
                "-c:a", "libmp3lame", "-q:a", "5",
                str(music_norm),
            ],
            check=True, capture_output=True,
        )
        # 混音：voice 1.0x（edge-tts 自带音量，不增）+ BGM 0.90x（归一后 ~-26dB，低于 voice 6dB）
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(silent_video),
                "-i", str(voice_mp3),
                "-i", str(music_norm),
                "-filter_complex", "[1:a]volume=1.0[v];[v][2:a]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(output_path),
            ],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(silent_video),
                "-i", str(voice_mp3),
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest", str(output_path),
            ],
            check=True, capture_output=True,
        )

    return output_path
