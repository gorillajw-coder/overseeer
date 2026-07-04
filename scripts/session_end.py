#!/usr/bin/env python3
"""Overseer — Claude Code 세션 종료 로거.

"/끝" 입력 시 트리거되어:
  1. 현재 세션의 .jsonl 대화 내용을 읽고
  2. (있으면) Development_plan_*.md 를 참조해
  3. Claude API로 요약을 생성한 뒤
  4. .claude-sessions/ 에 마크다운으로 저장하고
  5. git commit 하고
  6. 중앙 로그(~/.claude/overseer-log/<날짜>/)에 사본을 남긴다.
     → 다음날 아침 daily_digest.py 가 이 중앙 로그를 모아 다이제스트를 보낸다.

세션마다 조용히 기록만 한다 (알림/발송 없음). 발송은 daily_digest.py 담당.

사용법:
  python3 ~/.claude/scripts/session_end.py \
      --project-path <현재 프로젝트 경로> \
      --session-id <현재 세션 ID>

graceful fallback 원칙:
  - Development_plan_*.md 가 없어도 요약은 동작한다.
  - git repo가 아니면 커밋은 건너뛰고 중앙 로그만 남긴다.
  - 일부 단계가 실패해도 나머지 단계는 계속 진행한다.

의존성: 표준 라이브러리만 사용 (anthropic SDK 불필요).
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# --- 요약에 사용할 모델 (현행 Sonnet) ---
SUMMARY_MODEL = "claude-sonnet-4-6"
# Claude API에 보낼 대화 텍스트 최대 길이 (문자 기준, 너무 길면 앞부분을 잘라냄)
MAX_TRANSCRIPT_CHARS = 120_000
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def log(msg: str) -> None:
    print(f"[overseer] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# .env 로딩
# --------------------------------------------------------------------------- #
def load_env() -> None:
    """~/.claude/.env 를 읽어 os.environ 에 채운다 (이미 있는 값은 덮어쓰지 않음)."""
    env_path = Path.home() / ".claude" / ".env"
    if not env_path.exists():
        log(f".env 없음: {env_path} (환경변수로 대체 시도)")
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# --------------------------------------------------------------------------- #
# 세션 .jsonl 찾기 & 파싱
# --------------------------------------------------------------------------- #
def project_hash(project_path: str) -> str:
    """Claude Code의 projects 디렉토리 해시 규칙: 경로의 '/' 등을 '-'로 치환."""
    p = os.path.abspath(os.path.expanduser(project_path))
    return p.replace("/", "-").replace(".", "-").replace("_", "-")


def find_session_jsonl(project_path: str, session_id: str | None) -> Path | None:
    base = Path.home() / ".claude" / "projects"
    proj_dir = base / project_hash(project_path)

    if session_id:
        # 1) 정석 경로
        candidate = proj_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
        # 2) 어디에 있든 session_id로 글로벌 탐색 (버전별 경로 차이 대응)
        matches = list(base.glob(f"**/{session_id}.jsonl"))
        if matches:
            return matches[0]
        log(f".jsonl 을 찾지 못함 (session_id={session_id})")
        return None

    # session_id 미지정 → 해당 프로젝트의 가장 최근 .jsonl 자동 감지
    candidates = (
        sorted(proj_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if proj_dir.exists()
        else []
    )
    if candidates:
        return candidates[0]
    log(f"세션 .jsonl 을 찾지 못함 (프로젝트 디렉토리: {proj_dir})")
    return None


def _extract_text(content) -> str:
    """message.content (문자열 또는 블록 배열)에서 텍스트만 추출."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif block.get("type") == "tool_result":
                    inner = block.get("content")
                    if isinstance(inner, str):
                        parts.append(inner)
        return "\n".join(parts)
    return ""


def read_transcript(jsonl_path: Path) -> str:
    lines_out: list[str] = []
    for raw in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        text = _extract_text(msg.get("content")).strip()
        if text:
            lines_out.append(f"### {role}\n{text}")
    transcript = "\n\n".join(lines_out)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        # 뒷부분(최근 대화)을 보존
        transcript = transcript[-MAX_TRANSCRIPT_CHARS:]
    return transcript


# --------------------------------------------------------------------------- #
# Development plan 탐색
# --------------------------------------------------------------------------- #
def find_dev_plan(project_path: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(project_path, "Development_plan_*.md")))
    if not matches:
        return None
    try:
        return Path(matches[0]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Claude API 요약 (stdlib urllib — anthropic SDK 불필요)
# --------------------------------------------------------------------------- #
SUMMARY_PROMPT = """다음은 Claude Code 세션 대화 내용입니다.
{plan_section}아래 형식의 한국어 마크다운으로 **간략히** 요약하세요. 다른 말은 붙이지 마세요.

## 작업 목표
(한 줄)

## 완료
- (bullet)

## 다음
- (bullet)

## 특이사항
- (있으면, 없으면 생략)

---
[대화 내용]
{transcript}
"""


def summarize(transcript: str, dev_plan: str | None) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
        return "(요약 실패: ANTHROPIC_API_KEY 없음)"

    plan_section = ""
    if dev_plan:
        plan_section = (
            "참고용 계획서(Development plan)도 함께 제공합니다. 진행 상황을 계획서와 "
            "대조해서 요약하세요.\n\n[계획서]\n" + dev_plan[:20_000] + "\n\n"
        )

    prompt = SUMMARY_PROMPT.format(plan_section=plan_section, transcript=transcript)
    payload = {
        "model": SUMMARY_MODEL,
        "max_tokens": 1500,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = [
            b.get("text", "")
            for b in data.get("content", [])
            if b.get("type") == "text"
        ]
        return "".join(parts).strip() or "(요약 실패: 빈 응답)"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        log(f"Claude API 호출 실패 (HTTP {exc.code}): {detail}")
        return f"(요약 실패: HTTP {exc.code})"
    except Exception as exc:  # noqa: BLE001 - API 실패해도 파이프라인은 계속
        log(f"Claude API 호출 실패: {exc}")
        return f"(요약 실패: {exc})"


# --------------------------------------------------------------------------- #
# 파일 저장 + git
# --------------------------------------------------------------------------- #
def git_available(project_path: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", project_path, "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def write_and_commit(
    project_path: str, session_id: str, summary: str, hostname: str, now: dt.datetime
) -> str | None:
    """세션 마크다운을 저장하고 (git repo면) 커밋한다. 커밋 SHA를 반환(없으면 None)."""
    date_str = now.strftime("%Y-%m-%d")
    short_id = session_id[:6]
    project_name = os.path.basename(os.path.normpath(project_path))

    sessions_dir = Path(project_path) / ".claude-sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    out_file = sessions_dir / f"{date_str}_{project_name}_{short_id}.md"

    body = (
        f"# Session: {date_str} {project_name}\n\n"
        f"{summary}\n\n"
        f"## 기기\n{hostname}\n"
    )
    out_file.write_text(body, encoding="utf-8")
    log(f"세션 파일 저장: {out_file}")

    if not git_available(project_path):
        log("git repo 아님 → 커밋 건너뜀")
        return None

    first_line = next(
        (ln.lstrip("# ").strip() for ln in summary.splitlines() if ln.strip()),
        "session",
    )
    commit_msg = f"session: {date_str} {first_line}"[:100]
    try:
        subprocess.run(
            ["git", "-C", project_path, "add", str(out_file)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", project_path, "commit", "-m", commit_msg],
            check=True,
            capture_output=True,
        )
        sha = subprocess.run(
            ["git", "-C", project_path, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        log(f"커밋 완료: {sha[:8]}")
    except subprocess.CalledProcessError as exc:
        log(f"git 커밋 실패(변경 없음일 수 있음): {exc.stderr.decode(errors='replace') if exc.stderr else exc}")
        return None

    try:
        subprocess.run(
            ["git", "-C", project_path, "push"],
            check=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        log("push 완료 — 다른 기기/서버가 다음 동기화 때 이 기록을 받는다")
    except subprocess.TimeoutExpired:
        log("git push 시간 초과 (네트워크?) — 커밋은 로컬에 남아있음, 나중에 수동 push 필요")
    except subprocess.CalledProcessError as exc:
        log(f"git push 실패(오프라인/업스트림 없음일 수 있음, 커밋은 로컬에 남음): {exc.stderr.decode(errors='replace') if exc.stderr else exc}")

    return sha


# --------------------------------------------------------------------------- #
# 중앙 로그 (다음날 아침 daily_digest.py 가 모아서 발송)
# --------------------------------------------------------------------------- #
def central_log_dir() -> Path:
    """OVERSEER_LOG_DIR 환경변수 또는 ~/.claude/overseer-log."""
    override = os.environ.get("OVERSEER_LOG_DIR")
    return Path(override) if override else Path.home() / ".claude" / "overseer-log"


def write_central_log(
    date_str: str,
    project_name: str,
    session_id: str,
    summary: str,
    hostname: str,
    commit_url: str | None,
) -> None:
    """세션 요약 사본을 ~/.claude/overseer-log/<날짜>/ 에 남긴다."""
    day_dir = central_log_dir() / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    out = day_dir / f"{project_name}_{session_id[:6]}.md"
    body = f"# {project_name} ({hostname})\n\n{summary}\n"
    if commit_url:
        body += f"\n커밋: {commit_url}\n"
    out.write_text(body, encoding="utf-8")
    log(f"중앙 로그 기록: {out}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Overseer session-end logger")
    parser.add_argument(
        "--project-path", default=None, help="대상 프로젝트 경로 (생략 시 현재 폴더)"
    )
    parser.add_argument(
        "--session-id", default=None, help="세션 ID (생략 시 최근 세션 자동 감지)"
    )
    args = parser.parse_args()

    project_path = os.path.abspath(os.path.expanduser(args.project_path or os.getcwd()))
    session_id = args.session_id

    load_env()

    now = dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    hostname = socket.gethostname()
    project_name = os.path.basename(os.path.normpath(project_path))

    # 1. 대화 읽기 (session_id 없으면 최근 세션 자동 감지)
    jsonl = find_session_jsonl(project_path, session_id)
    if jsonl and not session_id:
        session_id = jsonl.stem
        log(f"세션 자동 감지: {session_id}")
    if not session_id:
        session_id = "manual"
    transcript = read_transcript(jsonl) if jsonl else ""
    if not transcript:
        transcript = "(세션 대화 내용을 찾지 못했습니다.)"

    # 2. 계획서
    dev_plan = find_dev_plan(project_path)
    if dev_plan:
        log("Development plan 발견 — 요약에 반영")

    # 3. 요약
    summary = summarize(transcript, dev_plan)

    # 4~5. 저장 + 커밋
    sha = write_and_commit(project_path, session_id, summary, hostname, now)

    # 커밋 링크
    commit_url = None
    repo_url = os.environ.get("GITHUB_REPO_URL", "").rstrip("/")
    if sha and repo_url:
        commit_url = f"{repo_url}/commit/{sha}"

    # 6. 중앙 로그 (다음날 아침 다이제스트용)
    write_central_log(date_str, project_name, session_id, summary, hostname, commit_url)

    log("완료 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
