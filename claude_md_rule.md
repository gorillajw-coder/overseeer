# 글로벌 CLAUDE.md 에 추가할 룰

아래 내용을 `~/.claude/CLAUDE.md` (모든 기기 공통) 에 붙여넣으세요.

---

## 세션 종료 룰 (Overseer)

사용자가 **"오늘은 끝!"** 이라고 입력하면, 다음 명령을 실행해서 이번 세션을 요약·기록한다:

```bash
python3 ~/.claude/scripts/session_end.py \
    --project-path "<현재 프로젝트 절대경로>" \
    --session-id "<현재 세션 ID>"
```

- `<현재 프로젝트 절대경로>`: 현재 작업 디렉토리(cwd)
- `<현재 세션 ID>`: 현재 Claude Code 세션의 ID

실행 후 스크립트가 출력하는 결과(`[overseer] ...`)를 사용자에게 간단히 보고한다.
