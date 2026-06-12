"""Demo: 不依赖 LLM/爬虫，跑通视频合成主流程。

10 段覆盖 12 张水墨背景中的 10 个意象，验证:
- 关键词匹配挑对应背景（不再 round-robin）
- Ken Burns 5% 缩放动效（zoompan）
- 背景音乐随机挑选
- 中文字幕卡正常渲染

用法:
    python -m tests.smoke_video
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.llm.base import ScriptSegment, VideoScript
from app.video.composer import compose_script


SCRIPT = VideoScript(
    title="水墨十二意象",
    subtitle="——一段 50 秒的视觉与听觉漫游",
    author="援翰写心",
    segments=[
        ScriptSegment(
            text="远山如黛，云雾相逐，归鸟掠过时，天地更静了。",
            visual_hint="远山归鸟",
        ),
        ScriptSegment(
            text="烟雨江南，湿了石阶，也湿了读信人的眼。",
            visual_hint="烟雨江南",
        ),
        ScriptSegment(
            text="墨竹一竿，风骨在叶，七贤若见，当与我同饮。",
            visual_hint="风骨墨竹",
        ),
        ScriptSegment(
            text="孤舟夜泊，水面如镜，潮声里听见的全是自己。",
            visual_hint="夜泊孤舟",
        ),
        ScriptSegment(
            text="夕阳一寸一寸落，黄昏也跟着沉了下去。",
            visual_hint="落日黄昏",
        ),
        ScriptSegment(
            text="雪夜孤灯，炉火微明，翻书的手指也暖了起来。",
            visual_hint="雪夜炉火",
        ),
        ScriptSegment(
            text="古道西风，瘦马一行，走了多久也走不出天涯。",
            visual_hint="古道天涯",
        ),
        ScriptSegment(
            text="庭院深深，门环锈绿，童年回望时已不可入。",
            visual_hint="庭院深深",
        ),
        ScriptSegment(
            text="一盏清茶，凉了又续，续的是日子，淡的是心。",
            visual_hint="清茶残茶",
        ),
        ScriptSegment(
            text="雨打芭蕉，凉了夏天，凉了母亲叫我的那一声。",
            visual_hint="雨打芭蕉",
        ),
    ],
    closing="水墨十二意象，淡到极致，便是浓。",
)


def main() -> None:
    work = settings.data_dir / "smoke"
    out = settings.output_dir / "smoke.mp4"
    if out.exists():
        out.unlink()
    print(f"[smoke] work_dir = {work}")
    print(f"[smoke] output   = {out}")
    compose_script(SCRIPT, work, out)
    print(f"[smoke] OK  size = {out.stat().st_size / 1024:.1f} KB")
    print(f"[smoke] 打开: open {out}")


if __name__ == "__main__":
    main()
