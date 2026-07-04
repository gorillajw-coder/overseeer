#!/usr/bin/env python3
"""Overseer — 유휴 세션 자동 스캔 ("/끝" 트리거 없이 세션 기록).

"/끝"을 안 쳐도, ~/.claude/projects/ 아래 모든 세션(.jsonl) 중 마지막 대화 후
IDLE_SECONDS(기본 1시간) 넘게 조용하고 아직 요약 안 된 것을 찾아 자동으로
session_end.py와 동일한 파이프라인(요약 → 저장 → 커밋 → push → 중앙 로그)을 돌린다.

기기 스케줄은 자유 — 이 스크립트는 몇 시에 돌든 "유휴 1시간+ & 미요약" 조건만 본다:
  - 서버: 매시 정각 cron
  - 맥: 로그인 시 1번 + 밤 11시 (launchd)
  - 회사PC: 저녁 10시 (작업 스케줄러)

각 기기가 push하고, daily_digest.py가 다음날 아침 pull해서 모아 보낸다.

사용법:
  python3 ~/.claude/scripts/nightly_session_scan.py
  python3 ~/.claude/scripts/nightly_session_scan.py --idle-seconds 1800
  python3 ~/.claude/scripts/nightly_session_scan.py --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import sys
import time
from pathlib import Path

# 같은 디렉토리의 session_end.py를 그대로 재사용 (요약/저장/커밋/push 로직 중복 없음)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_end as se  # noqa: E402

DEFAULT_IDLE_SECONDS = 3600


def log(msg: str) -> None:
    print(f"[overseer-scan] {msg}", file=sys.stderr)


def find_cwd(jsonl_path: Path) -> str | None:
    """세션 transcript에서 실제 프로젝트 경로(cwd)를 읽는다 — 인코딩된 폴더명보다 신뢰도 높음."""
    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def already_summarized(project_path: str, session_id: str) -> bool:
    sessions_dir = Path(project_path) / ".claude-sessions"
    if not sessions_dir.is_dir():
        return False
    short_id = session_id[:6]
    return any(sessions_dir.glob(f"*_{short_id}.md"))


def process_one(jsonl_path: Path, dry_run: bool) -> bool:
    session_id = jsonl_path.stem
    project_path = find_cwd(jsonl_path)
    if not project_path:
        log(f"cwd 못 찾음, 건너뜀: {jsonl_path}")
        return False
    if not Path(project_path).is_dir():
        log(f"프로젝트 경로 없음(삭제됨?), 건너뜀: {project_path}")
        return False
    if already_summarized(project_path, session_id):
        return False

    log(f"처리: {project_path} (session={session_id[:8]})")
    if dry_run:
        log("  (dry-run — 실제 처리 안 함)")
        return True

    se.load_env()
    now = dt.datetime.now()
    hostname = socket.gethostname()

    transcript = se.read_transcript(jsonl_path)
    if not transcript:
        transcript = "(세션 대화 내용을 찾지 못했습니다.)"
    dev_plan = se.find_dev_plan(project_path)
    summary = se.summarize(transcript, dev_plan)
    sha = se.write_and_commit(project_path, session_id, summary, hostname, now)

    commit_url = None
    import os

    repo_url = os.environ.get("GITHUB_REPO_URL", "").rstrip("/")
    if sha and repo_url:
        commit_url = f"{repo_url}/commit/{sha}"

    project_name = Path(project_path).name
    se.write_central_log(now.strftime("%Y-%m-%d"), project_name, session_id, summary, hostname, commit_url)
    return True


DEFAULT_MAX_AGE_DAYS = 3  # 이보다 오래된 세션은 (첫 실행 시 과거 이력 폭탄 방지) 건드리지 않음


def main() -> int:
    parser = argparse.ArgumentParser(description="Overseer idle-session scanner")
    parser.add_argument("--idle-seconds", type=int, default=DEFAULT_IDLE_SECONDS)
    parser.add_argument(
        "--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
        help="이보다 오래 전에 마지막으로 수정된 세션은 건너뜀 (0 = 제한 없음, 과거 이력 전부 처리)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.is_dir():
        log(f"projects 디렉토리 없음: {projects_root}")
        return 0

    now_ts = time.time()
    max_age_seconds = args.max_age_days * 86400 if args.max_age_days > 0 else None
    processed = 0
    for jsonl_path in projects_root.glob("*/*.jsonl"):
        try:
            mtime = jsonl_path.stat().st_mtime
        except OSError:
            continue
        age = now_ts - mtime
        if max_age_seconds and age > max_age_seconds:
            continue  # 너무 오래된 세션 — 첫 실행 시 몇 달치 이력이 한꺼번에 요약되는 걸 방지
        if age < args.idle_seconds:
            continue  # 아직 활동 중일 수 있음 — 건드리지 않음
        if process_one(jsonl_path, args.dry_run):
            processed += 1

    log(f"완료 — {processed}건 처리 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
