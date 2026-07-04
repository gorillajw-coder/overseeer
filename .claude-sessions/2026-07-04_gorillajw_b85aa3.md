# Session: 2026-07-04 gorillajw

## 작업 목표
Claude Code에서 Bash 도구가 모든 명령에 Exit code 1로 실패하는 원인 진단

## 완료
- `.bashrc`, `.profile`, `broot` launcher 등 셸 초기화 파일 이상 없음 확인
- `settings.json`, `settings.local.json` hook 설정 이상 없음 확인
- Claude Code 버전 2.1.199로 최신 버전 확인 (버전 미달 가설 배제)
- GitHub 이슈 검색으로 동일 증상 다수 리포트 확인 (exit 1, 출력 없음)
- 유력 원인 두 가지 좁힘: ①세션 CWD 오염 버그(#24143), ②환경 특이적 bash spawn 실패(`spawn /usr/bin/env bash ENOENT`)

## 다음
- **새 세션(새 터미널)** 을 열어서 bash 동작 여부 재확인 → 세션 오염 여부 판별
- 새 세션도 실패 시: `/usr/bin/env bash` 직접 실행 가능한지 일반 터미널에서 확인
- 계속 실패 시: Claude Code 재설치 고려

## 특이사항
- 회사컴과 홈서버 양쪽 모두 동일 증상 → 계정/클라이언트 레벨 문제 가능성 높음
- `.claude.json`에 `"cachedExtraUsageDisabledReason": "out_of_credits"` 캐시값 존재 (최신 상태 불명)
- 이슈 #12115, #41722 모두 "closed as not planned"으로 공식 해결책 없음

## 기기
gnollramy
