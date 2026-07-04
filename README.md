# Overseer

Claude Code 세션을 자동으로 요약해서 **기록**하고, 다음날 아침 전날 한 일을
**텔레그램 + 이메일**로 보내주는 도구. 여기에 텔레그램으로 서버의 Claude를
직접 부리는 **Claudy 봇**과 매주 서버 점검을 도는 **서버 유지보수 에이전트**가 얹혀 있다.

> **"/끝"** 한 마디면 — 사람이 추가 행동 없이 — 세션 요약이 만들어지고,
> 커밋되고, 중앙 로그에 쌓인다. 매일 아침 8시(KST) 전날 작업이 한 통으로 온다.
>
> "/끝"을 안 쳐도 된다 — `nightly_session_scan.py`가 각 기기에서 유휴 1시간+ 지난
> 미요약 세션을 자동으로 찾아 같은 파이프라인을 돌리고 **git push**까지 한다. 서버는
> 다이제스트 생성 시점에 추적 프로젝트들을 pull해서, 어느 기기에서 한 작업이든 모아 보낸다.

자세한 설계는 [`Development_plan_Overseer.md`](./Development_plan_Overseer.md) 참고.

---

## 동작 흐름

```
"/끝" (Claude Code 채팅 입력)
  → ~/.claude/CLAUDE.md 룰 트리거
  → scripts/session_end.py 실행
      ├── 세션 .jsonl 읽기 + Development_plan_*.md 참조(있으면)
      ├── Claude API로 요약 생성
      ├── .claude-sessions/<날짜>_<프로젝트>_<id>.md 저장 + git commit + push
      └── 중앙 로그 ~/.claude/overseer-log/<날짜>/ 에 사본 기록

기기별 스케줄 (서버: 매시 정각 cron / 맥: 로그인 시 + 밤 11시 launchd / 회사PC: 밤 10시 작업 스케줄러)
  → scripts/nightly_session_scan.py
      ├── ~/.claude/projects/ 전체에서 "유휴 1시간+ & 아직 요약 안 됨" 세션 탐지
      └── session_end.py와 동일한 파이프라인(요약→저장→커밋→push→중앙로그) 재사용

매일 08:00 KST (cron, 23:00 UTC)
  → scripts/daily_digest.py
      ├── Ops Dashboard 백엔드에서 추적 프로젝트 목록 조회 → git pull (다른 기기 push분 수신)
      ├── 전날(KST) 로컬 중앙 로그 + 추적 프로젝트들의 .claude-sessions/ 모아 중복 제거
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

Ops Dashboard (LAN + Tailscale, http://<서버>:8080/)
  → Homepage (dashboard/homepage/, systemd, Node.js, 127.0.0.1:8000)
      ├── 리소스(CPU/메모리/디스크): Netdata 링크 + 자체 위젯
      ├── dashboard/server/main.py (systemd, root, 127.0.0.1:8010) 를 서버사이드로 호출
      │     ├── 미등록(orphan) 프로세스 탐지 — ss + /proc/cgroup 교차 대조
      │     ├── 추적 프로젝트별 origin(GitHub) 대비 ahead/behind (백그라운드 git fetch)
      │     ├── 추적 프로젝트별 최근 세션 진행상황 (.claude-sessions/ 재사용)
      │     └── crontab 라벨링
      └── 바로가기: eocs / filemanager / wb-job-dashboard / Netdata
  → Netdata (네이티브 systemd, 포트 19999) — 자원/서비스별 그래프 + 알림 + 로그

텔레그램으로 "대시보드 최신화해줘" (Claudy 봇 경유)
  → agents/dashboard-config-sync (claude 에이전트)
      ├── /api/services, /api/cron 로 미등록 서비스/크론 드리프트 확인
      ├── /mnt/ssd, /mnt/hdd 스캔해 미등록 git 프로젝트 확인
      └── config.yaml에 추가할 항목을 제안만 함 — 사용자 확인 후 직접 적용
```

> Notion 연동은 제거됨 (이메일/텔레그램으로 대체).

---

## 구성

| 파일 | 역할 |
|------|------|
| `scripts/session_end.py` | "/끝" 트리거 — 세션 요약·저장·커밋·push·중앙로그 (발송 없음) |
| `scripts/nightly_session_scan.py` | "/끝" 없이도 유휴 세션 자동 감지·처리 (기기별 cron/launchd/작업 스케줄러) |
| `scripts/daily_digest.py` | 아침 다이제스트 — 추적 프로젝트 pull + 전날치 모아 텔레그램+이메일 발송 (cron) |
| `scripts/git_sync.py` | "깃 동기화해줘" (Claudy 봇) — 지금 바로 세션 체크포인트 + 추적 프로젝트 전체 pull |
| `agents/server-maintenance-runner.md` | 주간 서버 점검 에이전트 정의 (`~/.claude/agents/` 에 배포) |
| `bot/main.py` | Claudy 봇 — 텔레그램 ↔ 서버 claude 브리지 (systemd) |
| `claude_md_rule.md` | `~/.claude/CLAUDE.md` 에 붙일 "/끝" + "깃 동기화" 룰 |
| `.env.example` | 환경변수 템플릿 → `~/.claude/.env` |
| `dashboard/server/main.py` | Ops Dashboard 슬림 백엔드 — 미등록 프로세스/git 동기화/진행상황/크론 (systemd) |
| `dashboard/homepage/` | Ops Dashboard UI (Homepage, 업스트림 오픈소스 clone — 자체 .git 있어 nested repo라 커밋 안 됨) |
| `dashboard/homepage-config/` | Homepage 설정 YAML (우리가 직접 고친 것, 커밋됨) — 빌드 시 `homepage/config/`로 복사됨 |
| `agents/dashboard-config-sync.md` | 대시보드 config.yaml 드리프트(미등록 서비스/프로젝트/크론) 확인·제안 에이전트 (`~/.claude/agents/` 에 배포, Claudy 봇으로 트리거) |

스크립트는 표준 라이브러리만 사용한다 (anthropic SDK 불필요).

---

## 설치

### 1. 스크립트 배포
```bash
mkdir -p ~/.claude/scripts ~/.claude/agents
cp scripts/session_end.py scripts/daily_digest.py scripts/nightly_session_scan.py ~/.claude/scripts/
cp agents/server-maintenance-runner.md agents/dashboard-config-sync.md ~/.claude/agents/
```

**다른 기기(맥/윈도우)에 배포할 때**: 이 저장소를 pull해서 위와 동일하게 복사 + `.env` 설정(2번) 후,
그 기기에서 `git push`가 되는지(SSH 키/자격증명) 확인하고 `nightly_session_scan.py`용 스케줄만 등록하면 됨:

- **macOS**: `launchd` LaunchAgent — `RunAtLoad: true` + `StartCalendarInterval: {Hour: 23, Minute: 0}` 로 로그인 시 1번 + 밤 11시 실행
- **Windows**: 작업 스케줄러에서 매일 저녁 10시 트리거로 `python nightly_session_scan.py` 등록

이 세 스크립트는 Claude Code 자체와 무관한 순수 파이썬이라, 다른 기기의 Claude Code 권한 설정과는 상관없이 그냥 실행된다.

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

### 7. Ops Dashboard (선택, systemd + nginx + Netdata)

**7-1. 백엔드**
```bash
cd dashboard/server
python3.12 -m venv ../.venv
../.venv/bin/pip install -r requirements.txt
cp ../config/config.yaml.example ../config/config.yaml   # 경로/라벨 실값으로 채우기
sudo cp ../deploy/dashboard-backend.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now dashboard-backend.service
```

**7-2. Homepage (UI)** — 업스트림을 그대로 clone+build (repo에 커밋 안 됨):
```bash
cd dashboard
git clone --depth 1 https://github.com/gethomepage/homepage.git homepage
./deploy/build-homepage.sh
sudo cp deploy/homepage.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now homepage.service
```
설정은 `dashboard/homepage-config/*.yaml`에 커밋되어 있고(services.yaml에 백엔드 API 연결 이미 구성됨),
빌드 스크립트가 매번 `homepage/config/`로 복사한다. 설정을 고칠 땐 `homepage-config/`쪽을 수정할 것
(그래야 재빌드해도 안 사라짐). 재빌드 시 `./deploy/build-homepage.sh && sudo systemctl restart homepage.service`.

**7-3. Netdata** (리소스/서비스별 자원/알림/로그, 네이티브 systemd, 포트 19999):
```bash
wget -O /tmp/netdata-kickstart.sh https://get.netdata.cloud/kickstart.sh
sh /tmp/netdata-kickstart.sh
```

**7-4. nginx** — 기존 죽어있는 `listen 8080` 블록(`/etc/nginx/sites-available/homeserver`)을 Homepage(`127.0.0.1:8000`)용으로 재사용, LAN(192.168.0.0/24) + Tailscale(100.64.0.0/10) 허용 + `auth_basic` 추가. 정확한 diff는 핸드오프 메시지 참고.

접속: `http://<LAN 또는 Tailscale 주소>:8080/`

---

## 동작 보장 (graceful fallback)
- `Development_plan_*.md` 없어도 요약 동작.
- git repo 아니면 커밋 건너뛰고 중앙 로그만 남김.
- 다이제스트는 설정된 채널로만 발송 (한쪽 실패해도 다른 쪽 계속).
- 봇은 **허용 chat_id 외 메시지를 전부 무시** (보안상 전체 허용 금지).
- Ops Dashboard: `.claude-sessions/` 없는 프로젝트는 "기록 없음", git fetch 실패(네트워크/인증)는 "동기화 확인 불가"로 표시 — 에러로 죽지 않음.

---

## 보안
- 실제 비밀이 든 `.env` 는 `.gitignore` 로 커밋 차단.
- Ops Dashboard 백엔드(`dashboard-backend.service`, 포트 8010)는 `127.0.0.1`에만 바인딩, nginx로 노출 안 함 — Homepage가 서버사이드로만 호출.
- Homepage(`homepage.service`, 포트 8000)만 nginx `:8080` 블록을 통해 LAN + Tailscale 대역에 노출, `auth_basic`으로 한 겹 더 보호.
- Claudy 봇은 받은 메시지를 서버 claude 에 도구 사용 허용으로 넘기므로,
  **반드시 chat_id 화이트리스트**로 막아 쓴다.
- 토큰을 노출했다면 발급처에서 **재발급(rotate)** 권장.
