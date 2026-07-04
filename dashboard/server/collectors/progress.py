"""프로젝트별 최신 .claude-sessions/*.md 를 찾아 목표/완료/다음/특이사항 섹션을 파싱.

session_end.py가 이미 쓰고 있는 포맷을 그대로 재사용한다 (새 스키마 없음).
"""
from __future__ import annotations

import re
from pathlib import Path

from config import load_config

_SECTION_KEYS = ["작업 목표", "완료", "다음", "특이사항"]
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def _latest_session_file(sessions_dir: Path) -> Path | None:
    files = list(sessions_dir.glob("*.md"))
    if not files:
        return None

    def sort_key(f: Path):
        m = _DATE_PREFIX_RE.match(f.name)
        return (m.group(1) if m else "", f.stat().st_mtime)

    return max(files, key=sort_key)


def _parse_sections(text: str) -> dict:
    sections: dict[str, list[str]] = {k: [] for k in _SECTION_KEYS}
    current = None
    for line in text.splitlines():
        header = line.strip()
        if header.startswith("## "):
            name = header[3:].strip()
            current = name if name in sections else None
            continue
        if current and line.strip():
            sections[current].append(line.strip())
    return {
        "goal": " ".join(sections["작업 목표"]) or None,
        "done": sections["완료"],
        "next": sections["다음"],
        "notes": sections["특이사항"],
    }


def _project_progress(path: str, label: str) -> dict:
    sessions_dir = Path(path) / ".claude-sessions"
    if not sessions_dir.is_dir():
        return {"label": label, "path": path, "status": "no_sessions", "date": "기록 없음"}

    latest = _latest_session_file(sessions_dir)
    if latest is None:
        return {"label": label, "path": path, "status": "no_sessions", "date": "기록 없음"}

    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_sections(text)
    except OSError as exc:
        return {"label": label, "path": path, "status": "parse_error", "date": "파싱 실패", "message": str(exc)}

    m = _DATE_PREFIX_RE.match(latest.name)
    return {
        "label": label,
        "path": path,
        "status": "ok",
        "file": latest.name,
        "date": m.group(1) if m else None,
        **parsed,
    }


def snapshot() -> dict:
    cfg = load_config()
    projects = cfg.get("tracked_projects", [])
    return {
        "projects": [
            _project_progress(p["path"], p.get("label", p["path"]))
            for p in projects
        ]
    }
