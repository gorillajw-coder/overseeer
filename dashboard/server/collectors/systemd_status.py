"""추적 서비스 상태 + ss/proc-cgroup 교차 대조로 미등록(orphan) 리스닝 프로세스 탐지.

리소스 사용량/서비스별 자원 그래프는 Netdata가 담당한다 — 여기서는 "이 포트를 연 프로세스가
systemd 유닛인지, 그중 config.yaml에 등록된 것인지"만 판별한다. 이게 애초에 문제였던
"그때그때 nohup으로 띄운 스크립트"를 잡아내는 부분이다.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

import psutil

from config import load_config

_PID_RE = re.compile(r"pid=(\d+)")
_UNIT_RE = re.compile(r"([^/]+\.service)$")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _listening_ports() -> dict[int, int]:
    """포트 -> PID. `ss -tlnp`는 root로 실행되므로 모든 유저의 PID가 보인다."""
    out = _run(["ss", "-tlnp"])
    ports: dict[int, int] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or ":" not in parts[3]:
            continue
        try:
            port = int(parts[3].rsplit(":", 1)[-1])
        except ValueError:
            continue
        m = _PID_RE.search(line)
        if m:
            ports[port] = int(m.group(1))
    return ports


def _unit_for_pid(pid: int) -> str | None:
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text().strip()
    except OSError:
        return None
    m = _UNIT_RE.search(cgroup)
    return m.group(1) if m else None


def _process_info(pid: int) -> dict:
    try:
        p = psutil.Process(pid)
        cmdline = " ".join(p.cmdline()) or p.name()
        cwd = p.cwd()
        user = p.username()
        started_at = p.create_time()
    except psutil.Error:
        return {"pid": pid, "cmdline": "(조회 불가, 이미 종료됐을 수 있음)", "cwd": None, "user": None, "started_at": None}
    return {"pid": pid, "cmdline": cmdline, "cwd": cwd, "user": user, "started_at": started_at}


def _service_state(unit: str, user_unit: bool) -> str:
    unit_q = shlex.quote(unit)
    if user_unit:
        out = _run(["su", "-c", f"systemctl --user is-active {unit_q}", "gorillajw"])
    else:
        out = _run(["systemctl", "is-active", unit])
    return out.strip() or "unknown"


def snapshot() -> dict:
    cfg = load_config()
    tracked = {s["unit"]: s for s in cfg.get("tracked_services", [])}
    ignore_patterns = cfg.get("orphan_ignore_patterns", [])

    ports = _listening_ports()
    tracked_ports: list[dict] = []
    unlabeled_units: list[dict] = []
    orphans: list[dict] = []

    for port, pid in sorted(ports.items()):
        unit = _unit_for_pid(pid)
        if unit and unit in tracked:
            tracked_ports.append({"port": port, "unit": unit, "label": tracked[unit]["label"]})
        elif unit:
            unlabeled_units.append({"port": port, "unit": unit, **_process_info(pid)})
        else:
            info = _process_info(pid)
            info["ignored"] = any(p in (info.get("cmdline") or "") for p in ignore_patterns)
            orphans.append({"port": port, **info})

    tracked_status = [
        {
            "unit": unit,
            "label": meta["label"],
            "state": _service_state(unit, meta.get("user_unit", False)),
            "hidden": meta.get("hidden", False),
        }
        for unit, meta in tracked.items()
    ]
    tracked_visible = [s for s in tracked_status if not s["hidden"]]

    return {
        "tracked": tracked_status,
        "tracked_visible": tracked_visible,
        "tracked_ports": tracked_ports,
        "unlabeled_systemd": unlabeled_units,
        "orphans": orphans,
    }
