# 援翰写心 · 录

> 把公众号里的字句，录成一段可听可看的影。

把公众号文章（默认「援翰写心」）自动改写成 9:16 竖屏口播视频，
配 AI 配音 + 古风背景 + 淡雅背景音乐，用于视频号 / 抖音发布。

风格：**淡雅 · 隽永 · 一期一会**。纸黄底 + 墨色字 + 远山烟雨。

---

## 它能做什么

1. 抓取单篇公众号文章（mp.weixin.qq.com/s/...）
2. 可选：用搜狗微信按关键词搜索
3. 用 LLM 把正文改写成 3-5 段口播文案（带标题 / 副标题 / 落款 / 片尾）
4. 为每段单独合成 mp3 配音（Edge TTS · 晓晓）
5. 为每段渲染一张 9:16 字幕卡（PIL，淡雅渐变 + 竖排中文 + 自动换行）
6. 拼字幕卡 + 配音 + 背景音乐 → 一支 mp4

全程在本地跑，无云端依赖（除 LLM 和 TTS）。

---

## 一分钟上手

```bash
# 1) 装依赖
pip install -r requirements.txt
ffmpeg -version     # 需要 4.0+

# 2) 配环境变量（必填 LLM）
cp .env.example .env
# 编辑 .env 填入 ANTHROPIC_API_KEY（或 minimax 代理的 ANTHROPIC_BASE_URL + AUTH_TOKEN）

# 3) 生成占位的古风背景图和 BGM（只需跑一次）
python -m tests.generate_assets

# 4) 起 Web 后台
python main.py
# 打开 http://127.0.0.1:8765
```

在网页里贴一个公众号文章 URL，点「开始录制」即可。

---

## 命令行（不入 Web）

```bash
# 1) 灌文章进 SQLite
python -m tests.ingest <url1> <url2> ...

# 2) 端到端：从数据库取最新一条 → mock LLM → 合成视频
python -m tests.e2e --backend mock

# 3) 或指定 URL + 真实 LLM
python -m tests.e2e --url https://mp.weixin.qq.com/s/xxx --backend minimax
```

`output/<job_id>.mp4` 就是成片，`open output/xxx.mp4` 直接看。

---

## 架构

```
公众号 URL
    │
    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ app.crawler  │ →  │  app.llm     │ →  │  app.video   │ → output.mp4
│  (scrapling) │    │ (claude/     │    │ (PIL+ffmpeg+ │
│              │    │  minimax/    │    │  edge-tts)   │
└──────────────┘    │  mock)       │    └──────────────┘
                    └──────────────┘
```

| 模块 | 职责 |
|---|---|
| `app/crawler/wechat.py` | 抓单篇 + 搜狗搜索；用 `Fetcher`（HTTP only，`impersonate=chrome120`）|
| `app/llm/base.py` | `LLMBackend` 抽象 + `get_backend("claude"/"minimax"/"mock")` 工厂 |
| `app/llm/claude.py` | Anthropic 官方 API |
| `app/llm/minimax.py` | minimax 的 Anthropic 兼容端点 |
| `app/llm/mock.py` | 不联网，72 字一段硬切 |
| `app/tts/edge.py` | Edge TTS（晓晓，rate -8%），ffprobe 读真实时长 |
| `app/video/composer.py` | 字幕卡 + 配音 + 背景音 → mp4；ffmpeg filter_complex concat 保稳定 |
| `app/pipeline.py` | 后台线程编排 + JobStore |
| `app/server.py` | FastAPI 极简后台（`/` + `/api/generate` + `/api/job/{id}`）|

---

## LLM 后端

- **mock**：不联网，72 字一段硬切正文。跑通流水线用。
- **claude**：官方 Anthropic API，模型名走 `ANTHROPIC_MODEL`。
- **minimax**：minimax 的 Anthropic 兼容端点（`https://api.minimaxi.com/anthropic/`），
  模型名走 `ANTHROPIC_MODEL`（默认 `MiniMax-M3`）。
  这是一个强推理模型，会做 thinking，**`max_tokens` 必须 ≥ 16384**，否则只返回思考不返回文本。

`.env` 关键字段：

```bash
# 任选其一
ANTHROPIC_API_KEY=sk-ant-...                # claude
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic   # minimax
ANTHROPIC_AUTH_TOKEN=ey...                  # minimax 的 token
ANTHROPIC_MODEL=MiniMax-M3                  # 或 claude-sonnet-4-6
```

---

## 视频样式

`app/video/composer.py` 顶部 `Palette` 调色板：

| token | RGB | 用途 |
|---|---|---|
| `bg_top` | (242,236,222) | 米黄 |
| `bg_bottom` | (228,224,210) | 淡灰米 |
| `text_main` | (62,56,50) | 墨色 |
| `accent` | (158,122,92) | 淡赭（圆点装饰）|

默认三张古风背景（`assets/backgrounds/`）：
- `mountains.png` 远山
- `misty_rain.png` 烟雨
- `birds.png` 飞鸟

把新图片放进去（PNG，1080×1920），按 `bg_pool[i % len(bg_pool)]` 自动轮换。

`assets/music/placeholder_mood.mp3` 是 ffmpeg 生成的占位 BGM（30s 低频环境音）。
要换正版，把同名 mp3 覆盖即可。

---

## 测试

```bash
pytest -v                                    # 24 个单测（爬虫解析层）
python -m tests.e2e --backend mock           # 端到端，~1 分钟
```

fixture 在 `tests/fixtures/wechat_article.html`（从真文章裁的 ~450KB）。

---

## 已知边界

- 搜狗搜索：**搜不到「援翰写心」**（这个号没进 Sogou 索引），走 URL 模式。
- 公众号主页历史文章分页：需要 JS 渲染，没装 Chromium。
- `videos/9:16`：硬编码 1080×1920；要改去 `.env` 改 `VIDEO_WIDTH/HEIGHT`，
  背景图也要对应换。

---

## 目录

```
.
├── app/
│   ├── config.py             # 读 .env
│   ├── pipeline.py           # 后台任务编排
│   ├── server.py             # FastAPI
│   ├── crawler/wechat.py     # 抓文章 + 搜狗
│   ├── llm/                  # 可插拔 LLM
│   ├── tts/edge.py           # Edge TTS
│   └── video/composer.py     # 字幕卡 + ffmpeg 合成
├── tests/
│   ├── test_crawler.py       # 24 个单测
│   ├── e2e.py                # 端到端
│   ├── ingest.py             # 入库
│   ├── generate_assets.py    # 生成古风背景 + 占位 BGM
│   └── fixtures/
├── assets/
│   ├── backgrounds/          # PNG
│   └── music/                # mp3
├── data/                     # SQLite + 任务临时
├── output/                   # 成品 mp4
├── main.py                   # 启动入口
├── requirements.txt
└── .env.example
```
