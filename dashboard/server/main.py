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


@app.get("/api/issues")
def api_issues():
    """평소엔 안 봐도 되는 세부 정보를 다 걷어내고, "지금 확인이 필요한 것"만 모은 목록.
    비어있으면 전부 정상."""
    issues: list[dict] = []

    services = systemd_status.snapshot()
    for s in services["tracked"]:  # hidden 서비스도 문제가 있으면 여기엔 나와야 함
        if s["state"] != "active":
            issues.append({"label": s["label"], "detail": f"상태: {s['state']}"})

    orphan_count = len(services["orphans"])
    if orphan_count:
        issues.append({"label": "미등록 프로세스", "detail": f"{orphan_count}개 발견"})

    cache = git_sync.get_cache()
    for proj in cache.values():
        if proj.get("status") == "error":
            issues.append({"label": proj["label"], "detail": proj.get("summary", "동기화 확인 불가")})

    return {"issues": issues, "ok": not issues}
