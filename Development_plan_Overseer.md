# Development Plan: Claude Session Logger

## Goal
"오늘은 끝!" 입력 시 Claude Code 세션 내용을 자동 요약해서 Git 커밋 + Notion DB에 기록.

## Success Criteria
- "오늘은 끝!" 입력하면 사람이 추가 행동 없이 자동으로 전부 처리됨
- Notion DB에서 전체 프로젝트 진행 현황 총괄 가능

---

## Architecture

```
"오늘은 끝!" (Claude Code 채팅 입력)
→ CLAUDE.md 룰 트리거
→ session_end.py 실행
    ├── ~/.claude/projects/<project>/*.jsonl 읽기
    ├── Development_plan_<세션명>.md 읽기 (있으면)
    ├── Claude API로 요약 생성
    ├── .claude-sessions/<date>_<session_id>.md 로 저장
    ├── git add + commit
    └── Notion API로 DB row 추가
```

---

## Components

### 1. `~/.claude/scripts/session_end.py`
- 위치: 모든 기기 공통 경로
- 입력: 현재 프로젝트 경로, 세션 ID
- 동작:
  - `~/.claude/projects/<project_hash>/<session_id>.jsonl` 읽기
  - `Development_plan_*.md` 파일 프로젝트 루트에서 탐색
  - Claude API (`claude-sonnet-4-20250514`) 호출해서 요약 생성
  - `.claude-sessions/YYYY-MM-DD_<session_id_short>.md` 저장
  - `git add .claude-sessions/ && git commit -m "session: <날짜> <요약 첫줄>"`
  - Notion API로 row 추가

### 2. `~/.claude/CLAUDE.md` (global)
- 룰: "오늘은 끝!" 감지 시 아래 실행
  ```
  python3 ~/.claude/scripts/session_end.py --project-path <현재 프로젝트 경로> --session-id <현재 세션 ID>
  ```

### 3. Notion DB (신규 생성)
| 필드 | 타입 | 비고 |
|------|------|------|
| 세션명 | Title | `YYYY-MM-DD_<프로젝트명>` |
| 날짜 | Date | 세션 종료 시각 |
| 프로젝트 | Text | 프로젝트 폴더명 |
| 기기 | Text | hostname |
| 요약 | Text | Claude API 생성 |
| 커밋 | URL | GitHub 커밋 링크 |

---

## Environment Variables

```
NOTION_TOKEN=secret_xxx
NOTION_DB_ID=xxx
ANTHROPIC_API_KEY=xxx
GITHUB_REPO_URL=xxx  # 커밋 링크 생성용
```

`~/.claude/.env` 에 저장, session_end.py가 로드

---

## 요약 프롬프트 (Claude API)

```
다음은 Claude Code 세션 대화 내용입니다.
[Development_plan이 있으면] 계획서도 함께 참조하세요.

아래 형식으로 요약하세요:
- 작업 목표: (한 줄)
- 완료한 것: (bullet)
- 미완료/다음 할 것: (bullet)
- 특이사항: (있으면)
```

---

## File Output Example
`.claude-sessions/2026-06-10_cv-builder_a1b2c3.md`

```markdown
# Session: 2026-06-10 cv-builder

## 작업 목표
rfp_schema_update 반영 및 DAWASA JSON 출력 수정

## 완료
- schema 필드 3개 추가
- DAWASA WWTP 출력 테스트 통과

## 다음
- 나머지 프로젝트 JSON 업데이트

## 기기
Gnoramlly (DigitalOcean)
```

---

## Implementation Steps
1. Notion DB 생성 (API or 수동)
2. `~/.claude/.env` 작성
3. `~/.claude/scripts/session_end.py` 작성
4. `~/.claude/CLAUDE.md` 룰 추가
5. 테스트: 더미 프로젝트에서 "오늘은 끝!" 입력
6. 전체 기기에 스크립트 배포 (DigitalOcean, 맥북, 기타)

---

## Notes
- `.jsonl` 파일 경로는 Claude Code 버전에 따라 달라질 수 있음 → 실행 전 확인
- `Development_plan_*.md` 없어도 요약은 동작해야 함 (graceful fallback)
- git repo 없는 프로젝트면 커밋 스킵, Notion만 업데이트
