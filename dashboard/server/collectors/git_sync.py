"""추적 프로젝트별 origin 대비 ahead/behind — 백그라운드에서만 갱신, HTTP 요청은 캐시만 읽는다.

여러 기기 간 실시간 비교는 하지 않는다 — 이 기기의 로컬 체크아웃이 origin(GitHub)보다
얼마나 앞서/뒤처졌는지만 보여준다. 다른 기기가 origin에 푸시했다면 "behind"로 드러나는
식으로 간접적으로만 드러난다.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import time

from config import load_config

_cache: dict[str, dict] = {}

_GIT_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=8"


def get_cache() -> dict:
    return _cache


async def _run_git(path: str, args: list[str]) -> tuple[int, str, str]:
    """gorillajw 신원으로 git 실행 — 백엔드는 root로 돌지만(ss/crontab 때문), git은
    GitHub SSH 키/known_hosts가 있는 gorillajw로 su해서 실행해야 인증이 된다.
    """
    inner = " ".join(
        ["env", f"GIT_TERMINAL_PROMPT=0", f"GIT_SSH_COMMAND={shlex.quote(_GIT_SSH_COMMAND)}",
         "git", "-C", shlex.quote(path), *(shlex.quote(a) for a in args)]
    )
    proc = await asyncio.create_subprocess_exec(
        "su", "-c", inner, "gorillajw",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", "timeout"
    return proc.returncode, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()


async def _refresh_one(project: dict) -> dict:
    path = project["path"]
    branch = project.get("branch", "main")
    label = project.get("label", path)

    if not os.path.isdir(os.path.join(path, ".git")):
        return {"label": label, "path": path, "status": "no_git", "summary": "git 저장소 아님"}

    rc, _, err = await _run_git(path, ["fetch", "--quiet", "origin", branch])
    if rc != 0:
        return {
            "label": label, "path": path, "status": "error",
            "summary": "동기화 확인 불가", "message": err or "fetch 실패", "checked_at": time.time(),
        }

    rc, out, _ = await _run_git(path, ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"])
    ahead, behind = 0, 0
    if rc == 0 and out:
        try:
            ahead_s, behind_s = out.split()
            ahead, behind = int(ahead_s), int(behind_s)
        except ValueError:
            pass

    _, dirty_out, _ = await _run_git(path, ["status", "--porcelain", "--untracked-files=no"])
    dirty_count = len([l for l in dirty_out.splitlines() if l.strip()])

    _, current_branch, _ = await _run_git(path, ["branch", "--show-current"])

    summary = f"{ahead} ahead / {behind} behind"
    if dirty_count:
        summary += f", {dirty_count} dirty"

    return {
        "label": label,
        "path": path,
        "status": "ok",
        "summary": summary,
        "branch": current_branch or branch,
        "configured_branch": branch,
        "branch_drift": bool(current_branch) and current_branch != branch,
        "ahead": ahead,
        "behind": behind,
        "dirty": dirty_count,
        "checked_at": time.time(),
    }


async def refresh_all() -> None:
    cfg = load_config()
    projects = cfg.get("tracked_projects", [])
    for project in projects:
        try:
            result = await _refresh_one(project)
        except Exception as exc:  # 한 저장소 실패가 나머지에 영향 주면 안 됨
            result = {
                "label": project.get("label", project["path"]), "path": project["path"],
                "status": "error", "summary": "동기화 확인 불가", "message": str(exc),
            }
        _cache[project["path"]] = result


async def background_loop() -> None:
    cfg = load_config()
    interval = cfg.get("server", {}).get("refresh", {}).get("git_minutes", 10) * 60
    while True:
        await refresh_all()
        await asyncio.sleep(interval)
