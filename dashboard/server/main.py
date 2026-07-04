"""서버 운영 대시보드 — 슬림 백엔드.

리소스 모니터링은 Netdata(19999), UI는 Homepage가 담당한다. 여기서는 둘 다 안 해주는
3가지만 JSON으로 제공한다: 미등록 프로세스 탐지, git 동기화 상태, 프로젝트 진행상황.
로컬 전용 포트에서만 리슨하며 nginx로 노출하지 않는다 — Homepage가 서버사이드로 호출한다.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from collectors import cron_status, git_sync, progress, systemd_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(git_sync.background_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="Overseer Ops Backend", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/services")
def api_services():
    return systemd_status.snapshot()


@app.get("/api/cron")
def api_cron():
    return cron_status.snapshot()


@app.get("/api/git")
def api_git():
    cache = git_sync.get_cache()
    if not cache:
        return JSONResponse({"projects": [], "status": "pending"})
    return {"projects": list(cache.values()), "status": "ok"}


@app.get("/api/progress")
def api_progress():
    return progress.snapshot()
