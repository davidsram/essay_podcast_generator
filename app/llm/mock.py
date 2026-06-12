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
                ScriptSegment(text=s, visual_hint="烟雨远山", duration_hint=0)
                for s in picked
            ],
            closing="（下回，再录一段）",
        )
