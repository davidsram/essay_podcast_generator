"""生成 12 张水墨淡雅背景图（与 composer.BG_KEYWORDS 一一对应）和占位 BGM。

背景是 PIL primitives 画的轻量插画（米黄 / 灰墨 / 淡赭调色板），不用外部素材。
命名严格按 BG_KEYWORDS 字典的 key 走；改字典时要同步加新函数。
"""
from __future__ import annotations

import math
import random
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
BG_DIR = ROOT / "assets" / "backgrounds"
MUSIC_DIR = ROOT / "assets" / "music"

W, H = 1080, 1920  # 9:16

# 调色板：与 composer.PALETTE 同步
PAPER_TOP = (242, 236, 222)
PAPER_BOT = (228, 224, 210)
INK = (62, 56, 50)
INK_SOFT = (130, 120, 108)
INK_FAINT = (170, 162, 148)
RULE = (190, 178, 158)


# === 共享 helpers ===

def _gradient(img: Image.Image, top: tuple[int, int, int], bot: tuple[int, int, int],
              y0: int = 0, y1: int = H, x0: int = 0, x1: int = W) -> None:
    """在 img 上 y0..y1 行做 top→bot 垂直渐变。"""
    px = img.load()
    span = max(y1 - y0, 1)
    for y in range(y0, y1):
        t = (y - y0) / span
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        for x in range(x0, x1):
            px[x, y] = (r, g, b)


def _soft_mist(img: Image.Image, y0: int, y1: int, peak_alpha: int = 60) -> None:
    """在 y0..y1 行加一抹由浓转淡的白色雾。"""
    fog = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    fdraw = ImageDraw.Draw(fog)
    for y in range(y0, y1):
        a = int(peak_alpha * (1 - (y - y0) / max(y1 - y0, 1)))
        fdraw.line([(0, y), (W, y)], fill=(255, 255, 255, a))
    fog = fog.filter(ImageFilter.GaussianBlur(8))
    img.convert("RGBA").alpha_composite(fog)


def _mountain_layers(rng: random.Random, base_y_frac: float, color: tuple[int, int, int, int],
                     peaks: int, depth: int = 0) -> list[tuple[int, int]]:
    """三层山峰 polygon 顶点。depth=0 时从左下出发。"""
    base_y = int(H * base_y_frac)
    pts: list[tuple[int, int]] = [(0, base_y)]
    for i in range(1, peaks + 1):
        x = int(W * i / peaks)
        y = int(H * (base_y_frac - rng.uniform(0.05, 0.12)))
        pts.append((x, y))
    pts += [(W, base_y), (W, H), (0, H)]
    return pts


# === 1) misty_mountains 远山含雾 ===

def render_misty_mountains() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    # 渐变天空
    for y in range(0, int(H * 0.65)):
        t = y / (H * 0.65)
        for x in range(W):
            r = int(PAPER_TOP[0] * (1 - t) + 245 * t)
            g = int(PAPER_TOP[1] * (1 - t) + 242 * t)
            b = int(PAPER_TOP[2] * (1 - t) + 230 * t)
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img, "RGBA")
    layers = [
        (0.55, (170, 162, 148, 90), 5),
        (0.68, (130, 124, 110, 140), 7),
        (0.82, (95, 88, 76, 200), 11),
    ]
    rng = random.Random(42)
    for base_y, color, peaks in layers:
        pts = _mountain_layers(rng, base_y, color, peaks)
        draw.polygon(pts, fill=color)
    _soft_mist(img, int(H * 0.45), int(H * 0.60))
    out = BG_DIR / "misty_mountains.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


# === 2) rain_jiannan 烟雨江南 ===

def render_rain_jiannan() -> Path:
    rng = random.Random(7)
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, PAPER_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(280):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        ln = rng.randint(40, 110)
        a = rng.randint(20, 50)
        draw.line([(x, y), (x - 6, y + ln)], fill=(130, 124, 110, a), width=1)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    base_y = int(H * 0.78)
    pts: list[tuple[int, int]] = [(0, base_y)]
    peaks = 6
    for i in range(1, peaks + 1):
        x = int(W * i / peaks)
        y = base_y - rng.randint(60, 140)
        pts.append((x, y))
    pts += [(W, base_y), (W, H), (0, H)]
    draw = ImageDraw.Draw(img, "RGBA")
    draw.polygon(pts, fill=(95, 88, 76, 110))
    out = BG_DIR / "rain_jiannan.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 3) ink_bamboo 墨竹 ===

def render_ink_bamboo() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, PAPER_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(11)
    # 3-4 根竹竿（细竖线），用 INK 不同 alpha 制造远近
    culms = [(int(W * 0.30), 80), (int(W * 0.55), 90), (int(W * 0.78), 75)]
    for x, top in culms:
        draw.line([(x, top), (x + 12, H - 200)], fill=INK, width=4)
        # 竹节（横线）
        for j in range(top + 200, H - 250, 220):
            draw.line([(x - 8, j), (x + 20, j)], fill=INK, width=3)
    # 竹叶：每节附近 3-5 片斜短线
    for x, top in culms:
        for j in range(top + 200, H - 250, 220):
            for _ in range(rng.randint(3, 6)):
                dx = rng.randint(-30, 30)
                dy = rng.randint(-20, 20)
                length = rng.randint(30, 60)
                angle = rng.choice([-25, -10, 10, 25])
                ex = x + dx + length
                ey = j + dy - length // 3
                draw.line([(x + dx, j + dy), (ex, ey)], fill=INK_SOFT, width=2)
    out = BG_DIR / "ink_bamboo.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 4) lone_boat 孤舟 ===

def render_lone_boat() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, (220, 226, 230))  # 微偏冷，湖水感
    draw = ImageDraw.Draw(img, "RGBA")
    # 远处一抹山
    pts = [(0, int(H * 0.62)), (W // 3, int(H * 0.55)),
           (2 * W // 3, int(H * 0.58)), (W, int(H * 0.62)),
           (W, int(H * 0.68)), (0, int(H * 0.68))]
    draw.polygon(pts, fill=(150, 145, 132, 120))
    # 水平水波（几道横细线）
    for y in range(int(H * 0.70), H - 100, 80):
        rng = random.Random(y)
        x0 = rng.randint(0, 200)
        x1 = W - rng.randint(0, 200)
        draw.line([(x0, y), (x1, y)], fill=INK_FAINT, width=1)
    # 船：弯月
    boat_cx = int(W * 0.62)
    boat_y = int(H * 0.78)
    boat_w = 200
    boat_h = 50
    draw.arc(
        [(boat_cx - boat_w, boat_y - boat_h),
         (boat_cx + boat_w, boat_y + boat_h)],
        start=10, end=170, fill=INK, width=5,
    )
    # 桅杆
    draw.line([(boat_cx, boat_y - 10), (boat_cx, boat_y - 110)], fill=INK, width=3)
    # 帆（淡墨三角）
    draw.polygon(
        [(boat_cx, boat_y - 105), (boat_cx + 60, boat_y - 30), (boat_cx, boat_y - 30)],
        fill=INK_SOFT,
    )
    out = BG_DIR / "lone_boat.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 5) sunset_glow 落日 ===

def render_sunset_glow() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    # 渐变：上半偏米黄 → 中段淡赭 → 下半偏灰
    for y in range(0, int(H * 0.55)):
        t = y / (H * 0.55)
        r = int(PAPER_TOP[0] * (1 - t) + 232 * t)
        g = int(PAPER_TOP[1] * (1 - t) + 210 * t)
        b = int(PAPER_TOP[2] * (1 - t) + 190 * t)
        for x in range(W):
            img.putpixel((x, y), (r, g, b))
    for y in range(int(H * 0.55), H):
        t = (y - H * 0.55) / (H * 0.45)
        r = int(232 * (1 - t) + PAPER_BOT[0] * t)
        g = int(210 * (1 - t) + PAPER_BOT[1] * t)
        b = int(190 * (1 - t) + PAPER_BOT[2] * t)
        for x in range(W):
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img, "RGBA")
    # 落日
    sun_cx, sun_cy, sun_r = W // 2, int(H * 0.50), 110
    draw.ellipse(
        [(sun_cx - sun_r, sun_cy - sun_r), (sun_cx + sun_r, sun_cy + sun_r)],
        fill=(220, 170, 130, 200),
    )
    # 远山
    rng = random.Random(33)
    pts = [(0, int(H * 0.70))]
    for i in range(1, 5):
        x = int(W * i / 5)
        y = int(H * 0.70 - rng.uniform(0.04, 0.09))
        pts.append((x, y))
    pts += [(W, int(H * 0.70)), (W, H), (0, H)]
    draw.polygon(pts, fill=(95, 88, 76, 160))
    # 飞鸟归巢（3 只）
    for x, y in [(W // 4, int(H * 0.35)), (W // 2 + 50, int(H * 0.30)),
                 (3 * W // 4, int(H * 0.36))]:
        s = 12
        draw.line([(x - s, y), (x, y - s // 2)], fill=INK_SOFT, width=2)
        draw.line([(x, y - s // 2), (x + s, y)], fill=INK_SOFT, width=2)
    out = BG_DIR / "sunset_glow.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 6) snow_night 雪夜 ===

def render_snow_night() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    # 渐变：上深下浅
    for y in range(H):
        t = y / H
        r = int(170 * (1 - t * 0.4) + PAPER_TOP[0] * t * 0.4)
        g = int(170 * (1 - t * 0.4) + PAPER_TOP[1] * t * 0.4)
        b = int(178 * (1 - t * 0.4) + PAPER_TOP[2] * t * 0.4)
        for x in range(W):
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(99)
    # 雪花
    for _ in range(200):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        r = rng.randint(2, 4)
        draw.ellipse([(x - r, y - r), (x + r, y + r)], fill=(255, 255, 255, 220))
    # 远处孤灯：右下角一盏
    lamp_x, lamp_y = int(W * 0.78), int(H * 0.75)
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(halo)
    for r in range(160, 0, -20):
        a = int(60 * (1 - r / 160))
        hdraw.ellipse(
            [(lamp_x - r, lamp_y - r), (lamp_x + r, lamp_y + r)],
            fill=(240, 210, 150, a),
        )
    halo = halo.filter(ImageFilter.GaussianBlur(30))
    img.convert("RGBA").alpha_composite(halo)
    # 灯芯
    d2 = ImageDraw.Draw(img, "RGBA")
    d2.ellipse(
        [(lamp_x - 8, lamp_y - 8), (lamp_x + 8, lamp_y + 8)],
        fill=(250, 220, 170, 255),
    )
    out = BG_DIR / "snow_night.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


# === 7) ancient_path 古道 ===

def render_ancient_path() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, PAPER_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(101)
    # 远山一层
    pts = [(0, int(H * 0.60))]
    for i in range(1, 5):
        x = int(W * i / 5)
        y = int(H * 0.60 - rng.uniform(0.04, 0.08))
        pts.append((x, y))
    pts += [(W, int(H * 0.60)), (W, H), (0, H)]
    draw.polygon(pts, fill=(150, 145, 132, 130))
    # 落日（西边淡）
    draw.ellipse(
        [(int(W * 0.78), int(H * 0.42)), (int(W * 0.78) + 80, int(H * 0.42) + 80)],
        fill=(225, 195, 160, 180),
    )
    # 古道：从底部中心向远山弯去（贝塞尔近似）
    path_pts = [
        (W // 2 - 30, H),
        (W // 2 - 10, int(H * 0.85)),
        (W // 2 + 30, int(H * 0.75)),
        (W // 2 - 20, int(H * 0.68)),
    ]
    for i in range(len(path_pts) - 1):
        draw.line([path_pts[i], path_pts[i + 1]], fill=INK_SOFT, width=4)
    # 瘦马（一个长椭圆 + 几条腿）
    hx, hy = W // 2 + 10, int(H * 0.74)
    draw.ellipse([(hx - 30, hy - 10), (hx + 30, hy + 10)], fill=INK)
    for lx in (hx - 18, hx - 6, hx + 6, hx + 18):
        draw.line([(lx, hy + 10), (lx, hy + 30)], fill=INK, width=2)
    out = BG_DIR / "ancient_path.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 8) deep_courtyard 庭院 ===

def render_deep_courtyard() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, PAPER_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    # 院墙
    wall_color = (170, 158, 138, 255)
    draw.rectangle([(120, 700), (W - 120, H - 300)], fill=wall_color)
    # 屋顶斜线
    roof = [(120, 700), (W // 2, 600), (W - 120, 700)]
    draw.polygon(roof, fill=(110, 100, 85, 255))
    # 院门（中下方）
    door_w, door_h = 140, 240
    door_x = W // 2 - door_w // 2
    door_y = H - 300 - door_h
    draw.rectangle(
        [(door_x, door_y), (door_x + door_w, door_y + door_h)],
        fill=(85, 70, 55, 255),
    )
    # 窗（左右两扇小窗）
    for win_x in (220, W - 320):
        draw.rectangle(
            [(win_x, H - 480), (win_x + 100, H - 380)],
            fill=(105, 90, 75, 255),
        )
        draw.line(
            [(win_x + 50, H - 480), (win_x + 50, H - 380)],
            fill=INK, width=1,
        )
    # 院前石阶
    for i in range(3):
        y = H - 300 + i * 20
        draw.rectangle(
            [(140, y), (W - 140, y + 20)],
            fill=(190, 178, 158, 255),
        )
    out = BG_DIR / "deep_courtyard.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 9) cup_of_tea 清茶 ===

def render_cup_of_tea() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, PAPER_BOT)
    draw = ImageDraw.Draw(img, "RGBA")
    # 茶碗
    cup_cx, cup_cy, cup_w, cup_h = W // 2, int(H * 0.78), 360, 130
    draw.ellipse(
        [(cup_cx - cup_w, cup_cy - cup_h), (cup_cx + cup_w, cup_cy + cup_h)],
        fill=(200, 180, 145, 255),
    )
    # 碗内茶汤
    inner_w, inner_h = cup_w - 30, cup_h - 30
    draw.ellipse(
        [(cup_cx - inner_w, cup_cy - inner_h), (cup_cx + inner_w, cup_cy + inner_h)],
        fill=(155, 110, 75, 255),
    )
    # 茶气（3 缕波浪线）
    rng = random.Random(5)
    for k in range(3):
        base_x = cup_cx - 60 + k * 60
        pts = []
        for j in range(8):
            y = cup_cy - 130 - j * 40
            x = base_x + int(20 * math.sin(j * 0.8 + k))
            pts.append((x, y))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=INK_FAINT, width=2)
    out = BG_DIR / "cup_of_tea.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 10) rain_plantain 雨打芭蕉 ===

def render_rain_plantain() -> Path:
    rng = random.Random(13)
    img = Image.new("RGB", (W, H), PAPER_TOP)
    _gradient(img, PAPER_TOP, (210, 220, 210))
    draw = ImageDraw.Draw(img, "RGBA")
    # 3 片大芭蕉叶（用 polygon 模拟椭圆）
    leaves = [
        (W * 0.30, H * 0.45, 280, 600, -25),
        (W * 0.65, H * 0.40, 300, 700, 20),
        (W * 0.50, H * 0.30, 250, 550, 0),
    ]
    for cx, cy, w, h, rot in leaves:
        # 用椭圆旋转近似
        leaf = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(leaf)
        ld.ellipse(
            [(cx - w / 2, cy - h / 2), (cx + w / 2, cy + h / 2)],
            fill=(80, 110, 70, 200),
        )
        leaf = leaf.rotate(rot, resample=Image.BICUBIC)
        img.convert("RGBA").alpha_composite(leaf)
    # 雨丝
    d2 = ImageDraw.Draw(img, "RGBA")
    for _ in range(150):
        x = rng.randint(0, W)
        y = rng.randint(0, H)
        ln = rng.randint(30, 80)
        a = rng.randint(20, 50)
        d2.line([(x, y), (x - 4, y + ln)], fill=INK_SOFT + (a,), width=1)
    out = BG_DIR / "rain_plantain.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


# === 11) desert_smoke 大漠孤烟 ===

def render_desert_smoke() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    # 米黄 → 沙黄
    for y in range(H):
        t = y / H
        r = int(PAPER_TOP[0] * (1 - t) + 210 * t)
        g = int(PAPER_TOP[1] * (1 - t) + 188 * t)
        b = int(PAPER_TOP[2] * (1 - t) + 150 * t)
        for x in range(W):
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img, "RGBA")
    rng = random.Random(8)
    # 沙丘（弧形 polygon）
    for base_y, alpha in [(0.65, 80), (0.80, 160)]:
        pts = [(0, int(H * base_y))]
        for i in range(1, 7):
            x = int(W * i / 7)
            y = int(H * (base_y - rng.uniform(0.03, 0.07)))
            pts.append((x, y))
        pts += [(W, int(H * base_y)), (W, H), (0, H)]
        draw.polygon(pts, fill=(180, 150, 110, alpha))
    # 孤烟：底部一缕竖直的细线
    smoke_x = int(W * 0.55)
    smoke_base = int(H * 0.78)
    smoke = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(smoke)
    for i in range(40):
        y = smoke_base - i * 6
        w = max(2, int(8 + i * 0.5))
        a = max(0, 100 - i * 2)
        sd.line([(smoke_x - w // 2, y), (smoke_x + w // 2, y)],
                fill=(225, 215, 195, a), width=2)
    smoke = smoke.filter(ImageFilter.GaussianBlur(2))
    img.convert("RGBA").alpha_composite(smoke)
    # 驼影（一个椭圆 + 一条颈）
    hx, hy = int(W * 0.30), int(H * 0.78)
    d2 = ImageDraw.Draw(img, "RGBA")
    d2.ellipse([(hx - 30, hy - 15), (hx + 30, hy + 15)], fill=INK)
    d2.line([(hx + 25, hy - 5), (hx + 55, hy - 30)], fill=INK, width=4)
    d2.ellipse([(hx + 50, hy - 38), (hx + 65, hy - 25)], fill=INK)
    out = BG_DIR / "desert_smoke.png"
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


# === 12) rice_paper 宣纸留白 ===

def render_rice_paper() -> Path:
    img = Image.new("RGB", (W, H), PAPER_TOP)
    # 极淡渐变
    for y in range(H):
        t = y / H
        r = int(PAPER_TOP[0] * (1 - t * 0.3) + PAPER_BOT[0] * t * 0.3)
        g = int(PAPER_TOP[1] * (1 - t * 0.3) + PAPER_BOT[1] * t * 0.3)
        b = int(PAPER_TOP[2] * (1 - t * 0.3) + PAPER_BOT[2] * t * 0.3)
        for x in range(W):
            img.putpixel((x, y), (r, g, b))
    draw = ImageDraw.Draw(img, "RGBA")
    # 几行淡墨横（=书页/题字）
    rng = random.Random(2024)
    line_y = 700
    for k in range(5):
        # 每行长度不一，模拟残字
        ln = rng.randint(int(W * 0.30), int(W * 0.65))
        x0 = rng.randint(180, W - 180 - ln)
        # 用 5-10 个小段拼接，断笔
        cx = x0
        while cx < x0 + ln:
            seg = rng.randint(20, 50)
            draw.line([(cx, line_y), (cx + seg, line_y)], fill=INK, width=3)
            cx += seg + rng.randint(2, 12)
        line_y += rng.randint(80, 130)
    # 朱印（右下角小方块）
    seal_x, seal_y = W - 240, H - 300
    draw.rectangle(
        [(seal_x, seal_y), (seal_x + 100, seal_y + 100)],
        fill=(180, 70, 50, 230),
    )
    out = BG_DIR / "rice_paper.png"
    img.save(out, "PNG", optimize=True)
    return out


# === 13) 占位 BGM：低频环境音（保持向后兼容） ===

def render_placeholder_music() -> Path:
    """生成 60s 低频音，音量低，作为占位 BGM。"""
    out_wav = MUSIC_DIR / "placeholder_mood.wav"
    out_mp3 = MUSIC_DIR / "placeholder_mood.mp3"
    sr = 44100
    duration = 60.0
    n = int(sr * duration)

    freqs = [110.0, 165.0, 220.0]  # A2, E3, A3
    import struct

    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(n):
            t = i / sr
            v = 0.0
            for f in freqs:
                env = 0.5 + 0.5 * math.sin(2 * math.pi * 0.04 * t + freqs.index(f))
                v += 0.04 * env * math.sin(2 * math.pi * f * t)
            v += 0.005 * (random.random() * 2 - 1)
            v = max(-0.9, min(0.9, v)) * 0.25
            w.writeframes(struct.pack("<h", int(v * 32767)))
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(out_wav),
            "-c:a", "libmp3lame", "-q:a", "5",
            str(out_mp3),
        ],
        check=True, capture_output=True,
    )
    out_wav.unlink()
    return out_mp3


# === 入口 ===

_RENDERERS = [
    render_misty_mountains, render_rain_jiannan, render_ink_bamboo,
    render_lone_boat, render_sunset_glow, render_snow_night,
    render_ancient_path, render_deep_courtyard, render_cup_of_tea,
    render_rain_plantain, render_desert_smoke, render_rice_paper,
]


def main() -> None:
    BG_DIR.mkdir(parents=True, exist_ok=True)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    for fn in _RENDERERS:
        print(f"[bg] {fn.__name__:<24} -> {fn()}")
    print(f"[bgm] placeholder           -> {render_placeholder_music()}")


if __name__ == "__main__":
    main()
