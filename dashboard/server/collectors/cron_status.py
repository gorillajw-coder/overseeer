"""crontab -l 파싱 + config.yaml의 cron_labels로 사람이 읽을 라벨 붙이기."""
from __future__ import annotations

import subprocess

from config import load_config


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _label_for(command: str, labels: list[dict]) -> str | None:
    for entry in labels:
        if entry["match"] in command:
            return entry["label"]
    return None


def snapshot() -> dict:
    cfg = load_config()
    user = cfg.get("system", {}).get("crontab_user", "gorillajw")
    labels = cfg.get("cron_labels", [])

    out = _run(["crontab", "-l", "-u", user])
    jobs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        schedule, command = " ".join(parts[:5]), parts[5]
        jobs.append({
            "schedule": schedule,
            "command": command,
            "label": _label_for(command, labels) or command,
        })
    jobs.sort(key=lambda j: j["label"].casefold())
    return {"user": user, "jobs": jobs}
