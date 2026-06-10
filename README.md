# Overseer

Claude Code 세션을 자동으로 요약해서 **Git 커밋 + Notion DB**에 기록하는 도구.

> **"오늘은 끝!"** 한 마디면 — 사람이 추가 행동 없이 — 세션 요약이 만들어지고,
> 커밋되고, Notion DB에 한 줄로 쌓인다. 여러 기기·여러 프로젝트의 진행 현황을
> Notion 한 곳에서 총괄한다.

자세한 설계는 [`Development_plan_Overseer.md`](./Development_plan_Overseer.md) 참고.

---

## 동작 흐름

```
"오늘은 끝!" (Claude Code 채팅 입력)
  → ~/.claude/CLAUDE.md 룰 트리거
  → scripts/session_end.py 실행
      ├── ~/.claude/projects/<project>/<session>.jsonl 읽기
      ├── Development_plan_*.md 참조 (있으면)
      ├── Claude API로 요약 생성
      ├── .claude-sessions/<날짜>_<프로젝트>_<id>.md 저장
      ├── git add + commit
      └── Notion API로 DB 행 추가
```

---

## 설치

### 1. Notion 데이터베이스
이미 생성됨 — **Overseer 세션 로그** DB.
- DB ID: `111b3e294a6b434a85835e413e78c0b9`
- 필드: 세션명(Title) / 날짜(Date) / 프로젝트(Text) / 기기(Text) / 요약(Text) / 커밋(URL)

> ⚠️ Notion DB 페이지에서 **⋯ → Connections** 로 본인의 integration을 연결해야
> REST API(토큰)로 접근됩니다. 연결하지 않으면 `object_not_found` 오류가 납니다.

### 2. 스크립트 배포 (각 기기 공통)
```bash
mkdir -p ~/.claude/scripts
cp scripts/session_end.py ~/.claude/scripts/
pip install anthropic
```

### 3. 환경변수
```bash
cp .env.example ~/.claude/.env
# ~/.claude/.env 를 열어 실제 값(ANTHROPIC_API_KEY, NOTION_TOKEN 등)을 채운다
```

| 변수 | 설명 |
|------|------|
| `ANTHROPIC_API_KEY` | 요약 생성용 Anthropic API 키 |
| `NOTION_TOKEN` | Notion REST API 통합 토큰 (`ntn_` 시작) |
| `NOTION_DB_ID` | Notion 데이터베이스 ID |
| `GITHUB_REPO_URL` | 커밋 링크 생성용 (끝에 `/` 없이) |

### 4. CLAUDE.md 룰 추가
[`claude_md_rule.md`](./claude_md_rule.md) 의 내용을 `~/.claude/CLAUDE.md` 에 붙여넣는다.

### 5. 테스트
더미 프로젝트에서 **"오늘은 끝!"** 입력 → `.claude-sessions/` 에 파일이 생기고
Notion DB에 행이 추가되는지 확인.

또는 직접 실행:
```bash
python3 ~/.claude/scripts/session_end.py \
    --project-path "$(pwd)" \
    --session-id "<세션ID>"
```

---

## 동작 보장 (graceful fallback)
- `Development_plan_*.md` 가 없어도 요약은 동작한다.
- git repo가 아니면 커밋은 건너뛰고 Notion만 업데이트한다.
- `.jsonl` 경로는 Claude Code 버전에 따라 달라질 수 있어, session_id로 전역 탐색까지 시도한다.
- 일부 단계(API/Notion/git)가 실패해도 나머지 단계는 계속 진행하고 stderr에 로그를 남긴다.

---

## 보안
- 실제 비밀 값이 든 `.env` 는 `.gitignore` 로 커밋이 차단되어 있다.
- 토큰을 채팅 등에 노출했다면 발급처에서 **재발급(rotate)** 을 권장한다.
