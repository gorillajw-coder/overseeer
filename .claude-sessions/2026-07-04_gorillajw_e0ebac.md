# Session: 2026-07-04 gorillajw

## 작업 목표
Ops 대시보드(Homepage) UI/백엔드 개선 및 git 동기화 자동화 스크립트 추가

## 완료
- FileManager 프론트엔드 API 경로 오류 수정 (`/search`, `/files` → 상대경로)
- `git_sync.py` 온디맨드 동기화 스크립트 신규 생성 (세션 스캔 + 전체 저장소 pull 통합)
- CLAUDE.md에 "깃 동기화해줘" 룰 추가
- config.yaml에 nginx, homepage 서비스 추가 및 cron 라벨 정비
- `nightly_session_scan.py`에 저장소 루트 귀속 로직 추가 (pipeline 하위폴더 오귀속 수정)
- Homepage config YAML을 `dashboard/homepage-config/`로 분리하여 git 추적
- 대시보드 UI 개편: 그룹명/카드명 영어화, 설명 제거, 매트릭스 테마(검정+초록), 한글-영문 폰트 통일
- `/api/issues` 엔드포인트 추가 (서비스 오류·미등록 프로세스·git 에러 집계)
- `tracked_visible` 필드 추가 (hidden 서비스 카드에서 제외)
- EOCS remote를 HTTPS→SSH로 전환
- overseeer GitHub 레포 정리 (잘못 들어온 main 브랜치, claude/practical-maxwell 브랜치 삭제)

## 다음
- `sudo systemctl restart dashboard-backend.service` (백엔드 코드 변경 반영)
- `sudo systemctl restart homepage.service` (settings.yaml 색상/레이아웃 반영)
- Project Status 타일: 맥/회사PC 세션도 실시간 반영하려면 다이제스트 외 pull 주기 단축 검토
- overseeer를 main 브랜치로 병합(merge) 미완료

## 특이사항
- `/home/gorillajw` 홈 디렉터리 전체가 git 저장소로 잘못 구성된 것 발견 → origin만 제거해 overseeer와 분리
- dashboard/homepage/ 내부에 nested git repo가 있어 직접 추적 불가 → homepage-config/ 별도 디렉터리로 우회
- RussianTrans의 자동 세션 캡처가 번역 파이프라인 JSON 원문을 그대로 커밋한 이상 커밋 존재 (소급 수정 안 함)

## 기기
gnollramy
