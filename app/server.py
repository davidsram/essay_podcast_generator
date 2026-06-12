"""FastAPI 服务：极简 Web 后台。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.crawler.wcplus import WcplusClient, WcplusError
from app.pipeline import Job, launch, store

app = FastAPI(title="援翰写心 · 视频生成", version="0.1")

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"default_account": settings.wechat_account},
    )


@app.post("/api/generate")
def generate(
    url: str = Form(""),
    keyword: str = Form(""),
    nickname: str = Form(""),
    backend: str = Form("claude"),
) -> JSONResponse:
    if url:
        source, kind = url.strip(), "url"
    elif keyword:
        source, kind = keyword.strip(), "search"
    elif nickname:
        source, kind = nickname.strip(), "wcplus_account"
    else:
        raise HTTPException(400, "请提供公众号文章 URL / 搜索关键词 / 公众号昵称")
    job = launch(source, source_type=kind, llm_backend=backend)
    return JSONResponse({"job_id": job.job_id})


@app.get("/api/wcplus/articles")
def wcplus_articles(
    nickname: str = Query(..., description="公众号昵称"),
    limit: int = Query(10, ge=1, le=50),
) -> JSONResponse:
    """列出某公众号最近 N 篇文章（不含正文）。"""
    try:
        client = WcplusClient()
        acc = client.find_account(nickname)
        arts = client.list_articles(acc.biz, limit=limit)
    except WcplusError as e:
        raise HTTPException(503, str(e)) from e
    return JSONResponse(
        {
            "account": acc.to_dict(),
            "articles": [a.to_dict() for a in arts],
        }
    )


@app.get("/api/job/{jid}")
def job_status(jid: str) -> JSONResponse:
    j = store.get(jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    return JSONResponse(store.to_dict(j))


@app.get("/output/{filename}")
def output_file(filename: str) -> FileResponse:
    # 防止路径穿越
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "非法文件名")
    path = settings.output_dir / filename
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, media_type="video/mp4", filename=filename)
