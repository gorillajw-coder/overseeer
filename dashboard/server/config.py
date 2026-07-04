"""config.yaml 로더 — 대시보드가 추적하는 서비스/프로젝트/크론 라벨/리소스 임계치를 읽는다."""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


@functools.lru_cache(maxsize=1)
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} 없음 — config.yaml.example을 config.yaml로 복사하고 값을 채우세요."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)
