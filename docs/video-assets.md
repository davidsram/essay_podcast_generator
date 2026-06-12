# 视频素材说明

合成器（`app/video/composer.py`）依赖两类外部素材：

1. **背景图**（`assets/backgrounds/`）— 12 张水墨风 1080×1920 PNG
2. **背景音乐**（`assets/music/`）— 5 段 60s 纯音乐 mp3

任何一段缺失时，合成器都能**优雅降级**运行：
- 没背景图 → 用 PIL 程序化的米黄渐变
- 没音乐 → 静默（仅配音）

## 一、背景图

### 当前 12 张

| 文件名 | 意象 | BG_KEYWORDS 关键词 |
|---|---|---|
| `misty_mountains.png` | 远山含雾 | 山 / 远山 / 云 / 雾 / 归鸟 |
| `rain_jiannan.png` | 烟雨江南 | 雨 / 烟雨 / 江南 / 春雨 |
| `ink_bamboo.png` | 墨竹风骨 | 竹 / 墨竹 / 清风 / 节 / 风骨 |
| `lone_boat.png` | 孤舟夜泊 | 舟 / 船 / 渡 / 江 / 夜泊 |
| `sunset_glow.png` | 落日余晖 | 夕阳 / 落日 / 黄昏 / 余晖 |
| `snow_night.png` | 雪夜孤灯 | 雪 / 冬 / 夜 / 灯 / 炉 |
| `ancient_path.png` | 古道西风 | 古道 / 西风 / 瘦马 / 旅途 / 天涯 |
| `deep_courtyard.png` | 庭院深深 | 庭院 / 院 / 老屋 / 堂 / 厅 |
| `cup_of_tea.png` | 清茶淡盏 | 茶 / 茗 / 杯 / 盏 / 香 |
| `rain_plantain.png` | 雨打芭蕉 | 芭蕉 / 雨打 / 夏 / 荫 / 凉 |
| `desert_smoke.png` | 大漠孤烟 | 沙漠 / 大漠 / 孤烟 / 戈壁 / 西北 |
| `rice_paper.png` | 宣纸留白 | 纸 / 墨 / 书 / 字 / 卷 / 诗 / 题字 |

### 视觉匹配规则

合成器按 `ScriptSegment.visual_hint` 字段挑最匹配的背景：
1. 把 hint 文本与 `BG_KEYWORDS` 字典的 12 组关键词做"子串包含"匹配
2. **命中多个时取关键词最长的**（更具体）— 例如 "烟雨" 比 "雨" 优先
3. 都不命中 → 随机挑一张
4. 命中的文件坏了 → 返回 None（调用方走纯渐变）

### 替换为真图

当前 12 张是 PIL primitives 画的**占位**（米黄/灰墨调色板），足够测试但不"雅"。要升级为手绘或购买的图：

```bash
# 把图覆盖到对应文件名
cp my_real_mountains.png assets/backgrounds/misty_mountains.png
```

要求：
- **PNG，1080×1920（9:16）** — 不对的话合成器会 LANCZOS resize
- 低饱和度、米黄/灰墨调色板，与 `composer.PALETTE` 配色协调
- 主体偏中下，留出顶部装饰横线 + 中央字幕区域的空间

### 新增意象

1. 在 `app/video/composer.py` 的 `BG_KEYWORDS` 加一行：
   ```python
   "your_imagery": ["关键词1", "关键词2", ...],
   ```
2. 在 `tests/generate_assets.py` 加一个 `render_your_imagery()` 函数并塞进 `_RENDERERS` 列表
3. 在 `assets/backgrounds/` 放 `your_imagery.png`（同尺寸）
4. `python -m tests.generate_assets` 重生成

`tests/test_composer.py::TestBGKeywords::test_与_12_个_生成器_函数_一一对应` 会自动检查 key 与生成器函数的对齐。

## 二、背景音乐

### 当前 5 段

| 文件名 | 风格 | 合成方式 |
|---|---|---|
| `ancient_guqin.mp3` | 古琴 5 声 (CDEGA) 缓慢琶音 | sine + 二次谐波 + 指数衰减 |
| `flute_distant.mp3` | 笛/箫长音 + 缓 vibrato | 两条略 detune sine + 呼吸包络 |
| `piano_minimal.mp3` | 极简钢琴 C-Am-F-G 进行 | 三和弦 sine + 钢琴式指数衰减 |
| `ambient_pad.mp3` | 三和弦长 pad（220/330/440） | sine + 极缓起落包络 |
| `rain_white_noise.mp3` | 白噪音底层 + 偶发高频雨点 | 白噪 + 短 sine 雨点 |

加上 `placeholder_mood.mp3`（原占位），音乐池有 6 段。

合成器从池里**随机挑**一段。如果只有 1 段就固定用。挑选由 `_pick_music()` 完成。

### 替换为正版 CC0 音乐

推荐来源（按可商用 / 中式风格契合度排序）：

| 来源 | 链接 | 风格 | 许可 |
|---|---|---|---|
| FreePD.com | https://freepd.com/ | 公共领域合集 | CC0 / Public Domain |
| Incompetech (Kevin MacLeod) | https://incompetech.com/music/ | 单人/氛围/古典 | CC-BY 4.0 |
| 网易云独立音乐人 | 站内搜"古风 纯音乐" | 中国风 | 看作者页 |
| 站长素材 / 觅知网 | 站内搜"中国风 BGM" | 中式 | 多为免费 / 注明出处 |

替换方法：

```bash
cp my_real_guqin.mp3 assets/music/ancient_guqin.mp3
```

要求：
- **mp3 / wav / m4a 都行**（_pick_music 按后缀 glob）
- **60s 以上**（视频可能更长；ffmpeg 会按 voice_dur 裁到匹配长度）
- 淡雅、不喧宾夺主（人声压不过 BGM 时合成音量 0.15 就够）

### 新增 BGM

把任意 `.mp3 / .wav / .m4a` 放进 `assets/music/`，`_pick_music()` 下次调用就会进池。

要重生成占位 BGM：

```bash
python -m tests.generate_assets     # placeholder_mood.mp3
python -m tests.generate_music      # 5 段新 BGM
```

## 三、动效：Ken Burns

合成器对每段字幕卡用 ffmpeg `zoompan` 做**缓慢 5% 放大**，时长跟该段 TTS 配音声同步：

```
zoompan=z='1.0 + 0.05*on/(30*d)':   # z 从 1.0 缓慢放大到 1.05
       x='iw/2-(iw/zoom/2)':         # 居中
       y='ih/2-(ih/zoom/2)':         # 居中
       d={30*d}:s=1080x1920:fps=30
```

参数调优（`app/video/composer.py`）：
- **缩放幅度**：`0.05` 是当前值（5%）。要更明显改 0.08；更克制改 0.03
- **方向**：要平移 + 缩放，把 `x` / `y` 改为 `x='iw/2-(iw/zoom/2) - 30*on/(30*d)'`
- **fps**：30 是当前值；改 24 更电影感

## 四、调色板

`app/video/composer.py` 顶部 `Palette` 与字幕卡、背景图生成器（`tests/generate_assets.py`）共用：

| token | RGB | 用途 |
|---|---|---|
| `bg_top` | (242, 236, 222) | 米黄 |
| `bg_bottom` | (228, 224, 210) | 淡灰米 |
| `text_main` | (62, 56, 50) | 墨色 |
| `text_sub` | (130, 120, 108) | 淡墨 |
| `accent` | (158, 122, 92) | 淡赭（圆点装饰）|
| `rule` | (190, 178, 158) | 细线 |

要改主色调（例：偏冷绿），改这 6 个值即可，字幕卡、背景图生成器都跟着变。
