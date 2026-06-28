#!/usr/bin/env python3
"""Overseer — 아침 다이제스트.

전날(한국 시간 기준) "/끝" 으로 기록된 세션 요약들을 모아 하루치 다이제스트를
만들고, 텔레그램 + 이메일로 발송한다.

매일 한국시간 08:00 에 cron 으로 실행 (서버가 UTC면 23:00 UTC).

  python3 ~/.claude/scripts/daily_digest.py            # 어제(KST) 다이제스트
  python3 ~/.claude/scripts/daily_digest.py --date 2026-06-27   # 특정 날짜
  python3 ~/.claude/scripts/daily_digest.py --no-send   # 발송 없이 출력만

읽는 소스: ~/.claude/overseer-log/<날짜>/*.md  (session_end.py 가 남긴 중앙 로그)

graceful fallback:
  - 어제 기록이 없으면 짧은 "기록 없음" 알림만 보낸다.
  - 텔레그램/이메일 중 설정된 채널로만 보낸다 (한쪽 실패해도 다른 쪽 계속).

의존성: 표준 라이브러리만 사용.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

SUMMARY_MODEL = "claude-sonnet-4-6"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
KST = dt.timezone(dt.timedelta(hours=9))
TELEGRAM_MAX = 4000  # 텔레그램 메시지 한도(4096)보다 여유있게

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587


def log(msg: str) -> None:
    print(f"[overseer-digest] {msg}", file=sys.stderr)


def load_env() -> None:
    env_path = Path.home() / ".claude" / ".env"
    if not env_path.exists():
        log(f".env 없음: {env_path}")
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def central_log_dir() -> Path:
    override = os.environ.get("OVERSEER_LOG_DIR")
    return Path(override) if override else Path.home() / ".claude" / "overseer-log"


# --------------------------------------------------------------------------- #
# 어제 세션 모으기
# --------------------------------------------------------------------------- #
def collect_sessions(date_str: str) -> list[tuple[str, str]]:
    """(파일명, 본문) 목록. 없으면 빈 리스트."""
    day_dir = central_log_dir() / date_str
    if not day_dir.exists():
        return []
    out = []
    for f in sorted(day_dir.glob("*.md")):
        try:
            out.append((f.name, f.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


# --------------------------------------------------------------------------- #
# Claude 로 하루치 다이제스트 만들기 (stdlib urllib)
# --------------------------------------------------------------------------- #
DIGEST_PROMPT = """아래는 {date} 하루 동안 여러 Claude Code 세션에서 한 작업들의 요약 모음입니다.
이걸 종합해서, 다음날 아침에 읽을 **간략한 한국어 다이제스트**로 정리하세요.
형식:

📌 {date} 한 일

- 프로젝트별로 핵심만 1~3줄
- 마지막에 "오늘 이어서 할 것" 한두 줄

군더더기 없이 짧게. 마크다운 헤더(#)는 쓰지 마세요.

---
{sessions}
"""


def make_digest(date_str: str, sessions: list[tuple[str, str]]) -> str:
    joined = "\n\n".join(f"[{name}]\n{body}" for name, body in sessions)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY 없음 → 요약 없이 원본 이어붙임")
        return f"📌 {date_str} 한 일\n\n{joined}"

    prompt = DIGEST_PROMPT.format(date=date_str, sessions=joined[:120_000])
    payload = {
        "model": SUMMARY_MODEL,
        "max_tokens": 1200,
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
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        text = "".join(parts).strip()
        return text or f"📌 {date_str} 한 일\n\n{joined}"
    except Exception as exc:  # noqa: BLE001
        log(f"다이제스트 생성 실패 → 원본 이어붙임: {exc}")
        return f"📌 {date_str} 한 일\n\n{joined}"


# --------------------------------------------------------------------------- #
# 발송: 텔레그램
# --------------------------------------------------------------------------- #
def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 → 텔레그램 건너뜀")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in _chunks(text, TELEGRAM_MAX):
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as resp:
                json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            log(f"텔레그램 발송 실패 (HTTP {exc.code}): {exc.read().decode(errors='replace')}")
            return
        except Exception as exc:  # noqa: BLE001
            log(f"텔레그램 발송 실패: {exc}")
            return
    log(f"텔레그램 발송 완료 → chat {chat_id}")


# --------------------------------------------------------------------------- #
# 발송: 이메일
# --------------------------------------------------------------------------- #
def send_email(subject: str, text: str) -> None:
    to_addr = os.environ.get("EMAIL_TO")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    port = int(os.environ.get("SMTP_PORT", DEFAULT_SMTP_PORT))
    from_addr = os.environ.get("EMAIL_FROM", user or to_addr or "")
    if not to_addr or not user or not password:
        log("EMAIL_TO / SMTP_USER / SMTP_PASS 미설정 → 이메일 건너뜀")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(text)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
        log(f"이메일 발송 완료 → {to_addr}")
    except Exception as exc:  # noqa: BLE001
        log(f"이메일 발송 실패: {exc}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Overseer daily digest")
    parser.add_argument("--date", default=None, help="대상 날짜 YYYY-MM-DD (생략 시 어제 KST)")
    parser.add_argument("--no-send", action="store_true", help="발송 없이 출력만")
    args = parser.parse_args()

    load_env()

    if args.date:
        date_str = args.date
    else:
        # 한국시간 기준 '어제'
        now_kst = dt.datetime.now(dt.timezone.utc).astimezone(KST)
        date_str = (now_kst.date() - dt.timedelta(days=1)).isoformat()

    sessions = collect_sessions(date_str)
    if not sessions:
        log(f"{date_str} 기록 없음")
        body = f"📌 {date_str}\n\n어제 기록된 작업이 없습니다."
    else:
        log(f"{date_str} 세션 {len(sessions)}건 → 다이제스트 생성")
        body = make_digest(date_str, sessions)

    if args.no_send:
        print(body)
        return 0

    send_telegram(body)
    send_email(f"[Overseer] {date_str} 한 일", body)
    log("완료 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
