"""主流程编排：抓文章 → LLM 改写 → 合成视频。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

from app.config import settings
from app.crawler.cache import fetch_article_cached
from app.crawler.wechat import fetch_article
from app.crawler.wcplus import WcplusError
from app.llm.base import VideoScript, get_backend
from app.video.composer import compose_script

logger = logging.getLogger(__name__)


@dataclass
class Job:
    job_id: str
    status: str = "pending"  # pending / fetching / summarizing / synthesizing / done / failed
    progress: int = 0
    message: str = ""
    article: dict | None = None
    script_json: dict | None = None
    output_path: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class JobStore:
    """Demo 用的内存任务存储。"""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        jid = uuid.uuid4().hex[:12]
        job = Job(job_id=jid)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, jid: str) -> Job | None:
        with self._lock:
            return self._jobs.get(jid)

    def update(self, jid: str, **kwargs: object) -> None:
        with self._lock:
            job = self._jobs.get(jid)
            if not job:
                return
            for k, v in kwargs.items():
                setattr(job, k, v)

    def to_dict(self, job: Job) -> dict:
        d = asdict(job)
        d["script_preview"] = (job.script_json or {}).get("title", "")
        return d


store = JobStore()


# === 主流程 ===

def run_pipeline(
    job_id: str,
    source: str,
    *,
    source_type: Literal["url", "search", "wcplus_account"] = "url",
    llm_backend: str = "claude",
    on_update: Callable[[str], None] | None = None,
) -> None:
    """在后台线程跑的同步流水线。"""
    def emit(**kw: object) -> None:
        store.update(job_id, **kw)
        if on_update:
            on_update(job_id)

    try:
        # 1) 抓取
        emit(status="fetching", progress=10, message="正在抓取文章…")
        if source_type == "url":
            article = fetch_article(source)
        elif source_type == "search":
            from app.crawler.wechat import search_articles
            arts = search_articles(source, limit=1)
            if not arts:
                raise RuntimeError(f"未找到关于「{source}」的公众号文章")
            article = fetch_article(arts[0].url)
        elif source_type == "wcplus_account":
            # source 格式："<nickname>"，按该公众号最新一篇文章抓
            from app.crawler.wcplus import WcplusClient
            client = WcplusClient()
            acc = client.find_account(source)
            arts = client.list_articles(acc.biz, limit=1)
            if not arts:
                raise RuntimeError(f"公众号「{source}」没有任何文章")
            # 有 wcplus id 时优先走本地缓存（tests/wcplus_cache.py 预热的）
            article = fetch_article_cached(arts[0].url, wcplus_id=arts[0].id)
        else:
            raise RuntimeError(f"未知的 source_type: {source_type}")
        emit(
            article={
                "title": article["title"],
                "author": article["author"],
                "account": article.get("account", ""),
                "url": article["url"],
                "publish_time": article.get("publish_time", ""),
            },
            progress=30,
            message=f"已抓取：{article['title']}",
        )

        # 2) LLM 总结
        emit(status="summarizing", progress=40, message="正在改写成视频脚本…")
        if not article.get("body"):
            raise RuntimeError("文章正文为空（可能反爬被拦截或 URL 失效），无法总结")
        backend = get_backend(llm_backend)
        script: VideoScript = backend.summarize_to_script(
            title=article["title"],
            author=article["author"] or article.get("account") or settings.wechat_account,
            body=article["body"],
            target_seconds=settings.video_duration,
        )
        if not script.segments:
            raise RuntimeError("LLM 未生成任何段落，body 可能太短或被过滤")
        emit(
            script_json={
                "title": script.title,
                "subtitle": script.subtitle,
                "author": script.author,
                "closing": script.closing,
                "segments": [
                    {"text": s.text, "visual_hint": s.visual_hint, "duration_hint": s.duration_hint}
                    for s in script.segments
                ],
            },
            progress=60,
            message="脚本生成完成",
        )

        # 3) 视频合成
        emit(status="synthesizing", progress=70, message="正在合成视频…")
        work_dir: Path = settings.data_dir / job_id
        out_path: Path = settings.output_dir / f"{job_id}.mp4"
        compose_script(script, work_dir, out_path)
        emit(output_path=str(out_path), status="done", progress=100, message="完成")

    except Exception as e:  # noqa: BLE001
        logger.exception("pipeline failed for job %s", job_id)
        emit(status="failed", error=str(e), message=f"失败：{e}")


def launch(
    source: str,
    source_type: Literal["url", "search", "wcplus_account"] = "url",
    llm_backend: str = "claude",
) -> Job:
    """创建任务并启动后台线程。"""
    job = store.create()
    t = threading.Thread(
        target=run_pipeline,
        args=(job.job_id, source),
        kwargs={"source_type": source_type, "llm_backend": llm_backend},
        daemon=True,
    )
    t.start()
    return job
