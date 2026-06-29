# Overseer

Claude Code 세션을 자동으로 요약해서 **기록**하고, 다음날 아침 전날 한 일을
**텔레그램 + 이메일**로 보내주는 도구. 여기에 텔레그램으로 서버의 Claude를
직접 부리는 **Claudy 봇**과 매주 서버 점검을 도는 **서버 유지보수 에이전트**가 얹혀 있다.

> **"/끝"** 한 마디면 — 사람이 추가 행동 없이 — 세션 요약이 만들어지고,
> 커밋되고, 중앙 로그에 쌓인다. 매일 아침 8시(KST) 전날 작업이 한 통으로 온다.

자세한 설계는 [`Development_plan_Overseer.md`](./Development_plan_Overseer.md) 참고.

---

## 동작 흐름

```
"/끝" (Claude Code 채팅 입력)
  → ~/.claude/CLAUDE.md 룰 트리거
  → scripts/session_end.py 실행
      ├── 세션 .jsonl 읽기 + Development_plan_*.md 참조(있으면)
      ├── Claude API로 요약 생성
      ├── .claude-sessions/<날짜>_<프로젝트>_<id>.md 저장 + git commit
      └── 중앙 로그 ~/.claude/overseer-log/<날짜>/ 에 사본 기록

매일 08:00 KST (cron, 23:00 UTC)
  → scripts/daily_digest.py
      ├── 전날(KST) 중앙 로그 모으기
      ├── Claude API로 하루치 다이제스트 생성
      └── 텔레그램 + 이메일 발송

매주 수요일 17:30 KST (cron, 08:30 UTC)
  → agents/server-maintenance-runner (claude 에이전트, 구독 모델)
      ├── apt 업데이트·업그레이드
      ├── 디스크·메모리·swap 점검
      ├── 서비스 상태·로그 감사·SSH 감사
      └── ~/.claude/overseer-log/maintenance/maintenance.log 에 리포트 기록

텔레그램 @noticlaudy_bot (양방향, bot/)
  → 허용 chat_id 의 메시지를 서버 claude(헤드리스)로 전달
  → MCP(Gmail/캘린더 등) + bash 로 처리 후 응답
```

> Notion 연동은 제거됨 (이메일/텔레그램으로 대체).

---

## 구성

| 파일 | 역할 |
|------|------|
| `scripts/session_end.py` | "/끝" 트리거 — 세션 요약·저장·커밋·중앙로그 (발송 없음) |
| `scripts/daily_digest.py` | 아침 다이제스트 — 전날치 모아 텔레그램+이메일 발송 (cron) |
| `agents/server-maintenance-runner.md` | 주간 서버 점검 에이전트 정의 (`~/.claude/agents/` 에 배포) |
| `bot/main.py` | Claudy 봇 — 텔레그램 ↔ 서버 claude 브리지 (systemd) |
| `claude_md_rule.md` | `~/.claude/CLAUDE.md` 에 붙일 "/끝" 룰 |
| `.env.example` | 환경변수 템플릿 → `~/.claude/.env` |

스크립트는 표준 라이브러리만 사용한다 (anthropic SDK 불필요).

---

## 설치

### 1. 스크립트 배포
```bash
mkdir -p ~/.claude/scripts ~/.claude/agents
cp scripts/session_end.py scripts/daily_digest.py ~/.claude/scripts/
cp agents/server-maintenance-runner.md ~/.claude/agents/
```

### 2. 환경변수
```bash
cp .env.example ~/.claude/.env   # 그 서버에서 직접 실제 값 채우기
chmod 600 ~/.claude/.env
```
| 변수 | 설명 |
|------|------|
| `ANTHROPIC_API_KEY` | 요약 생성용 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 다이제스트 발송 + 봇 허용 chat_id |
| `EMAIL_TO` / `SMTP_USER` / `SMTP_PASS` | Gmail SMTP (SMTP_PASS = 앱 비밀번호 16자) |
| `GITHUB_REPO_URL` | 커밋 링크 생성용 |

### 3. CLAUDE.md 룰
[`claude_md_rule.md`](./claude_md_rule.md) 내용을 `~/.claude/CLAUDE.md` 에 추가.

### 4. 아침 다이제스트 cron (08:00 KST = 23:00 UTC)
```bash
( crontab -l 2>/dev/null; echo "0 23 * * * /usr/bin/python3 ~/.claude/scripts/daily_digest.py >> ~/.claude/overseer-log/digest.log 2>&1" ) | crontab -
```
즉시 테스트: `python3 ~/.claude/scripts/daily_digest.py --no-send`

### 5. 서버 유지보수 에이전트 cron (매주 수요일 17:30 KST = 08:30 UTC)
```bash
( crontab -l 2>/dev/null; echo "30 8 * * 3 ~/.local/bin/claude -p 'gnollramy 서버 주간 점검을 실행해줘. server-maintenance-runner 에이전트를 사용해서.' --allowedTools 'Bash,Read,Write,Edit' >> ~/.claude/overseer-log/maintenance/maintenance.log 2>&1" ) | crontab -
```
로그 위치: `~/.claude/overseer-log/maintenance/maintenance.log`

### 6. Claudy 봇 (선택, systemd)
```bash
cd bot
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
sudo cp claudy-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now claudy-bot.service
```

---

## 동작 보장 (graceful fallback)
- `Development_plan_*.md` 없어도 요약 동작.
- git repo 아니면 커밋 건너뛰고 중앙 로그만 남김.
- 다이제스트는 설정된 채널로만 발송 (한쪽 실패해도 다른 쪽 계속).
- 봇은 **허용 chat_id 외 메시지를 전부 무시** (보안상 전체 허용 금지).

---

## 보안
- 실제 비밀이 든 `.env` 는 `.gitignore` 로 커밋 차단.
- Claudy 봇은 받은 메시지를 서버 claude 에 도구 사용 허용으로 넘기므로,
  **반드시 chat_id 화이트리스트**로 막아 쓴다.
- 토큰을 노출했다면 발급처에서 **재발급(rotate)** 권장.
