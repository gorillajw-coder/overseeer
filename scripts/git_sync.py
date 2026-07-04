#!/usr/bin/env python3
"""Overseer — 온디맨드 git 동기화 ("깃 동기화해줘" 같은 요청에 Claudy 봇이 실행).

즉흥적으로 판단하지 않고 항상 똑같이 두 가지를 한다:
  1. 이 기기의 현재/최근 세션을 지금 바로 체크포인트 (idle 시간 기다리지 않음)
     → nightly_session_scan.py와 동일한 파이프라인 재사용 (요약→저장→커밋→push)
  2. 추적 중인 프로젝트 저장소를 전부 pull (다른 기기가 올린 변경사항 받기)

사용법:
  python3 ~/.claude/scripts/git_sync.py
  python3 ~/.claude/scripts/git_sync.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_digest as dd  # noqa: E402
import nightly_session_scan as nss  # noqa: E402


def log(msg: str) -> None:
    print(f"[git-sync] {msg}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Overseer on-demand git sync")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log("1/2 — 이 기기의 세션 체크포인트 중 (idle 대기 없이 지금 바로)...")
    processed = nss.scan(idle_seconds=0, max_age_days=1, dry_run=args.dry_run)
    log(f"  → {processed}건 요약·커밋·push 완료")

    log("2/2 — 추적 프로젝트 pull 중...")
    paths = dd.tracked_project_paths()
    if not paths:
        log("  → 대시보드 백엔드에서 추적 프로젝트 목록을 못 가져옴 (건너뜀)")
    elif args.dry_run:
        log(f"  → (dry-run) {len(paths)}개 저장소 pull 예정: {', '.join(paths)}")
    else:
        dd.pull_tracked_projects(paths)
        log(f"  → {len(paths)}개 저장소 pull 완료")

    log("동기화 완료 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
