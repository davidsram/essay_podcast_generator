"""Mock LLM 后端：把原文裁成 N 段直接当口播，方便没 API key 也能跑端到端。"""
from __future__ import annotations

import re

from app.llm.base import LLMBackend, ScriptSegment, VideoScript


def _split_sentences(text: str) -> list[str]:
    """按句末标点切。"""
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[。！？!?\.])", text)
    return [p.strip() for p in parts if p.strip()]


def _merge_into_segments(sentences: list[str], max_chars: int = 100) -> list[str]:
    """把句子合并成每段 max_chars 内的口播段。"""
    segs: list[str] = []
    buf = ""
    for s in sentences:
        if len(buf) + len(s) <= max_chars:
            buf = (buf + " " + s).strip() if buf else s
        else:
            if buf:
                segs.append(buf)
            buf = s
    if buf:
        segs.append(buf)
    return segs


_MOCK_HINTS = (
    "夜色远山", "朝雾初晴", "草原落日", "雨巷青瓦", "丛林薄暮",
    "江湖夜泊", "庭院深秋", "烛影摇红", "工厂车间", "旧信老照片",
)


def _pick_mock_hint(title: str, seg_index: int, seg_text: str) -> str:
    """mock 专用：从 10 个文艺意象里按 (title + seg_index + seg_text) 哈希选一个。
    同一段确定性；不同段区分；不同文章也区分（title 影响 hash）。"""
    h = sum(ord(c) for c in title + seg_text) + seg_index * 31
    return _MOCK_HINTS[h % len(_MOCK_HINTS)]


class MockBackend(LLMBackend):
    name = "mock"

    def summarize_to_script(
        self,
        title: str,
        author: str,
        body: str,
        target_seconds: int = 75,
    ) -> VideoScript:
        sentences = _split_sentences(body)
        target_chars = target_seconds * 4
        merged = _merge_into_segments(sentences, max_chars=72)
        used = 0
        picked: list[str] = []
        for seg in merged:
            if used + len(seg) > target_chars:
                break
            picked.append(seg)
            used += len(seg)
            if len(picked) >= 6:
                break
        if not picked and merged:
            picked = merged[:4]

        return VideoScript(
            title=title,
            subtitle=f"—{author}·记",
            author=author,
            segments=[
                ScriptSegment(
                    text=s,
                    # 每段给不同 hint：基于段文字 hash，落到 5 个文艺意象里挑一个
                    # （避免所有段用同一 hint 导致拍立得面板重复）
                    visual_hint=_pick_mock_hint(title, i, s),
                    duration_hint=0,
                )
                for i, s in enumerate(picked)
            ],
            closing="（下回，再录一段）",
        )
