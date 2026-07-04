# Session: 2026-07-04 claudy-workspace

## 작업 목표
홈서버 Tailscale SSH 접속 문제 해결 및 각종 서버 설정 작업

## 완료
- Tailscale UFW 포트(41641) 허용으로 맥 → 홈서버 SSH 접속 문제 해결
- 아이폰(Termius)에서도 SSH 접속 확인
- VS Code Remote SSH 설정 (`ssh homeserver`)
- rclone 설치 및 Google Drive 마운트 (`~/gdrive`), systemd 자동 마운트 등록
- gsuite-mcp(Node.js) 설치 시도 (Gmail MCP 연결은 미완)
- daily-digest 스크립트 구현 및 테스트 발송 완료 (텔레그램+이메일)
- RussianTrans overnight 파이프라인 정상 작동 확인 (본문 번역 진행 중)
- 번역 모델 추천 메모 저장 (`~/projects/translation-models.md`)
- RussianTrans 서식 정리 규칙 저장 (`~/projects/russiantrans-formatting-rules.md`)

## 다음
- daily-digest cron 등록 (02:30 UTC)
- Gmail MCP 연결 (gsuite-mcp OAuth 인증 완료 필요)
- 장윤주(코이카)에게 이메일 draft 작성
- RussianTrans 서식 규칙 구현
- MP/FS 4장 번역 완료 확인

## 특이사항
- SSH 문제 원인: Tailscale UDP 41641 포트 미허용 (51820만 열려있었음)
- `tailscale down` 실수로 로그아웃 발생, 브라우저 재인증으로 복구
- sudo NOPASSWD 미설정 상태라 비밀번호를 채팅에 입력한 보안 이슈 있음

## 기기
gnollramy
