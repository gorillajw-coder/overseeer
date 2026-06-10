#!/usr/bin/env python3
"""Overseer — Claude Code 세션 종료 로거.

"오늘은 끝!" 입력 시 트리거되어:
  1. 현재 세션의 .jsonl 대화 내용을 읽고
  2. (있으면) Development_plan_*.md 를 참조해
  3. Claude API로 요약을 생성한 뒤
  4. .claude-sessions/ 에 마크다운으로 저장하고
  5. git commit 하고
  6. Notion DB에 행을 추가한다.

사용법:
  python3 ~/.claude/scripts/session_end.py \
      --project-path <현재 프로젝트 경로> \
      --session-id <현재 세션 ID>

graceful fallback 원칙:
  - Development_plan_*.md 가 없어도 요약은 동작한다.
  - git repo가 아니면 커밋은 건너뛰고 Notion만 업데이트한다.
  - 일부 단계가 실패해도 나머지 단계는 계속 진행한다.
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
NOTION_VERSION = "2022-06-28"
# Notion rich_text 한 블록 최대 길이 (실제 한도 2000)
NOTION_TEXT_LIMIT = 1900


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


def find_session_jsonl(project_path: str, session_id: str) -> Path | None:
    base = Path.home() / ".claude" / "projects"
    # 1) 정석 경로
    candidate = base / project_hash(project_path) / f"{session_id}.jsonl"
    if candidate.exists():
        return candidate
    # 2) 어디에 있든 session_id로 글로벌 탐색 (버전별 경로 차이 대응)
    matches = list(base.glob(f"**/{session_id}.jsonl"))
    if matches:
        return matches[0]
    log(f".jsonl 을 찾지 못함 (session_id={session_id})")
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
# Claude API 요약
# --------------------------------------------------------------------------- #
SUMMARY_PROMPT = """다음은 Claude Code 세션 대화 내용입니다.
{plan_section}아래 형식의 한국어 마크다운으로 요약하세요. 다른 말은 붙이지 마세요.

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
    try:
        import anthropic
    except ImportError:
        log("anthropic 패키지가 없습니다. `pip install anthropic` 후 재시도하세요.")
        return "(요약 실패: anthropic 패키지 미설치)"

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
        return "(요약 실패: ANTHROPIC_API_KEY 없음)"

    plan_section = ""
    if dev_plan:
        plan_section = (
            "참고용 계획서(Development plan)도 함께 제공합니다. 진행 상황을 계획서와 "
            "대조해서 요약하세요.\n\n[계획서]\n" + dev_plan[:20_000] + "\n\n"
        )

    prompt = SUMMARY_PROMPT.format(plan_section=plan_section, transcript=transcript)

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=SUMMARY_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
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
        return sha
    except subprocess.CalledProcessError as exc:
        log(f"git 커밋 실패(변경 없음일 수 있음): {exc.stderr.decode(errors='replace') if exc.stderr else exc}")
        return None


# --------------------------------------------------------------------------- #
# Notion
# --------------------------------------------------------------------------- #
def _rt(text: str) -> list[dict]:
    return [{"text": {"content": text[:NOTION_TEXT_LIMIT]}}]


def notion_add_row(
    title: str,
    date_str: str,
    project_name: str,
    hostname: str,
    summary: str,
    commit_url: str | None,
) -> None:
    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DB_ID")
    if not token or not db_id:
        log("NOTION_TOKEN / NOTION_DB_ID 미설정 → Notion 업데이트 건너뜀")
        return

    properties = {
        "세션명": {"title": [{"text": {"content": title}}]},
        "날짜": {"date": {"start": date_str}},
        "프로젝트": {"rich_text": _rt(project_name)},
        "기기": {"rich_text": _rt(hostname)},
        "요약": {"rich_text": _rt(summary)},
    }
    if commit_url:
        properties["커밋"] = {"url": commit_url}

    # 전체 요약은 페이지 본문(children)에도 넣어 길이 제한을 우회
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rt(chunk)},
        }
        for chunk in _chunks(summary, NOTION_TEXT_LIMIT)
    ] or None

    payload: dict = {"parent": {"database_id": db_id}, "properties": properties}
    if children:
        payload["children"] = children

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if 200 <= resp.status < 300:
                log("Notion 행 추가 완료")
            else:
                log(f"Notion 응답 코드 {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        log(f"Notion 추가 실패 (HTTP {exc.code}): {detail}")
    except urllib.error.URLError as exc:
        log(f"Notion 네트워크 오류: {exc}")


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] if text else []


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Overseer session-end logger")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    project_path = os.path.abspath(os.path.expanduser(args.project_path))
    session_id = args.session_id

    load_env()

    now = dt.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    hostname = socket.gethostname()
    project_name = os.path.basename(os.path.normpath(project_path))
    title = f"{date_str}_{project_name}"

    # 1. 대화 읽기
    jsonl = find_session_jsonl(project_path, session_id)
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

    # 6. Notion
    notion_add_row(title, date_str, project_name, hostname, summary, commit_url)

    log("완료 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
