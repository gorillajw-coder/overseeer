#!/usr/bin/env python3
"""Overseer — Hermes가 만든 요약을 최종 기록.

사용법:
  python3 finalize_pending_summary.py <job.json> --summary-file summary.md
  python3 finalize_pending_summary.py <job.json> --summary "..."

Hermes(Grok OAuth)가 요약을 생성한 뒤 이 스크립트로
.write_and_commit + 중앙로그 + job 완료 처리를 한다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_end as se  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job", help="pending job json path")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--summary", help="summary markdown text")
    g.add_argument("--summary-file", help="path to summary markdown file")
    args = parser.parse_args()

    job_path = Path(args.job)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("type") != "session_summary":
        print(f"unsupported job type: {job.get('type')}", file=sys.stderr)
        return 1

    if args.summary_file:
        summary = Path(args.summary_file).read_text(encoding="utf-8").strip()
    else:
        summary = (args.summary or "").strip()
    if not summary:
        print("empty summary", file=sys.stderr)
        return 1

    se.load_env()
    project_path = job["project_path"]
    session_id = job["session_id"]
    hostname = job.get("hostname") or "unknown"
    now = dt.datetime.fromisoformat(job["created_at"]) if job.get("created_at") else dt.datetime.now()

    sha = se.write_and_commit(project_path, session_id, summary, hostname, now)
    commit_url = None
    repo_url = os.environ.get("GITHUB_REPO_URL", "").rstrip("/")
    if sha and repo_url:
        commit_url = f"{repo_url}/commit/{sha}"
    se.write_central_log(
        job.get("date") or now.strftime("%Y-%m-%d"),
        job.get("project_name") or Path(project_path).name,
        session_id,
        summary,
        hostname,
        commit_url,
    )

    job["status"] = "done"
    job["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    job["commit_sha"] = sha
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    # move to done/
    done = job_path.parent / "done"
    done.mkdir(exist_ok=True)
    job_path.rename(done / job_path.name)
    print(f"[finalize] done → {done / job_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
