"""Claudy — @noticlaudy_bot 텔레그램 ↔ 서버 claude CLI 브리지.

허용된 chat_id 에서 온 메시지를 서버의 claude(헤드리스, 구독 로그인)로 넘기고
답을 돌려준다. claude 는 MCP(Gmail/캘린더/드라이브 등) + bash 를 쓸 수 있으므로,
**반드시 chat_id 화이트리스트로 막는다.**

명령:
  /start   안내 + 내 chat_id 확인
  /new     대화 맥락 초기화 (다음 메시지는 새 세션)
  /digest  오늘(또는 어제) 다이제스트 즉시 받기
  그 외 텍스트 → claude 에게 그대로 전달 (이전 맥락 이어감)

설정(~/.claude/.env 또는 환경변수):
  TELEGRAM_BOT_TOKEN   봇 토큰
  TELEGRAM_CHAT_ID     허용 chat_id (쉼표로 여러 개 가능; ALLOWED_CHAT_IDS 도 인식)
  CLAUDE_BIN           claude 실행 경로 (기본 ~/.local/bin/claude)
  CLAUDY_WORKDIR       claude 작업 디렉토리 (기본 ~/claudy-workspace)
  CLAUDY_CLAUDE_ARGS   claude 추가 인자 (기본 --dangerously-skip-permissions)
  CLAUDY_TIMEOUT       호출 타임아웃 초 (기본 300)
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ~/.claude/.env 를 우선 로드(토큰·chat_id 공유), 그다음 봇 로컬 .env
load_dotenv(Path.home() / ".claude" / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("claudy-bot")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))
WORKDIR = Path(os.environ.get("CLAUDY_WORKDIR", str(Path.home() / "claudy-workspace")))
CLAUDE_ARGS = shlex.split(
    os.environ.get("CLAUDY_CLAUDE_ARGS", "--dangerously-skip-permissions")
)
TIMEOUT = int(os.environ.get("CLAUDY_TIMEOUT", "300"))
TELEGRAM_MAX = 4000


def _allowed_chat_ids() -> set[int]:
    raw = (
        os.environ.get("ALLOWED_CHAT_IDS")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


ALLOWED = _allowed_chat_ids()
# 대화 맥락 이어가기: chat 단위로 직전 호출이 있었는지 추적 → --continue 사용
_has_context: dict[int, bool] = {}
# claude 호출 직렬화(구독 쿼터 보호 + 세션 충돌 방지)
_claude_lock = asyncio.Lock()


def _is_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED


async def _reply_chunked(update: Update, text: str) -> None:
    text = text.strip() or "(빈 응답)"
    for i in range(0, len(text), TELEGRAM_MAX):
        await update.message.reply_text(text[i : i + TELEGRAM_MAX])


async def _run_claude(prompt: str, chat_id: int) -> str:
    """claude 헤드리스 호출. 직전 맥락이 있으면 --continue 로 이어감."""
    args = [CLAUDE_BIN, "-p", *CLAUDE_ARGS]
    if _has_context.get(chat_id):
        args.append("--continue")
    args.append(prompt)

    WORKDIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")

    async with _claude_lock:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKDIR),
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return f"⏱️ 처리 시간 초과({TIMEOUT}s). 더 작게 나눠서 시켜보세요."

    if proc.returncode != 0:
        msg = (err or b"").decode(errors="replace").strip()
        log.error("claude 실패 rc=%s: %s", proc.returncode, msg[:500])
        return f"⚠️ claude 실행 오류 (rc={proc.returncode})\n{msg[:1000]}"

    _has_context[chat_id] = True
    return (out or b"").decode(errors="replace")


# --------------------------------------------------------------------------- #
# 핸들러
# --------------------------------------------------------------------------- #
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ok = _is_allowed(chat_id)
    await update.message.reply_text(
        "안녕하세요, Claudy예요 🤖\n"
        "서버에 붙은 Claude로 이메일·캘린더·파일·서버작업까지 처리해드려요.\n"
        "그냥 자연어로 시키면 됩니다. (이전 대화 맥락 이어감)\n\n"
        "· /new — 대화 맥락 초기화\n"
        "· /digest — 다이제스트 즉시\n\n"
        f"이 채팅 chat_id: {chat_id}\n"
        f"허용 상태: {'✅ 허용됨' if ok else '🚫 미허용 (관리자에게 chat_id 등록 요청)'}"
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        return
    _has_context[chat_id] = False
    await update.message.reply_text("🆕 대화 맥락을 초기화했어요. 새로 시작합니다.")


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not _is_allowed(chat_id):
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    # 인자로 날짜(YYYY-MM-DD) 주면 그 날짜, 아니면 어제(스크립트 기본)
    date_arg = context.args[0] if context.args else None
    script = str(Path.home() / ".claude" / "scripts" / "daily_digest.py")
    cmd = ["python3", script, "--no-send"]
    if date_arg:
        cmd += ["--date", date_arg]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    await _reply_chunked(update, (out or b"").decode(errors="replace"))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not _is_allowed(chat_id):
        log.warning("차단된 chat_id=%s 메시지 무시", chat_id)
        return
    if not text:
        return
    log.info("chat=%s 요청: %r", chat_id, text[:120])
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    result = await _run_claude(text, chat_id)
    await _reply_chunked(update, result)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("핸들러 예외 (봇은 계속 동작)", exc_info=context.error)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN 미설정 (~/.claude/.env 확인)")
    if not ALLOWED:
        raise SystemExit(
            "허용 chat_id 없음 — TELEGRAM_CHAT_ID/ALLOWED_CHAT_IDS 설정 필요 "
            "(보안상 전체 허용은 막아둠)"
        )
    log.info("Claudy 시작. 허용 chat_id=%s, workdir=%s", ALLOWED, WORKDIR)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(on_error)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
