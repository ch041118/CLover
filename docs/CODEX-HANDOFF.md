# Codex 작업 인계

2026-09-25. 저장소: https://github.com/ch041118/CLover

## 목적과 현재 상태

사회복지사가 모든 요청을 읽고 배정하던 업무 중 명확한 일반 요청을 자동화한다. 어르신은 마이크를 누른 채 말하고 손을 떼면 접수한다. 가입·주소·기기 설정은 요양보호사가 돕는다. 사전 동의 범위 안의 일반 일정은 자동 확정하고 수행 불가·모호함·배정 실패를 담당 사회복지사에게 넘긴다.

기획은 SERVICE-PLAN.md, 실제 동작·업데이트·남은 제약은 FLOW-V2.md, 검증 결과는 루트 VALIDATION.md를 먼저 읽는다. 이전 문서의 ‘모든 요청 사전 승인’과 ‘확인 발화 후 제출’은 새 음성 흐름에 적용하지 않는다.

## 핵심 코드

- backend/app/flow_api.py: 대리 등록, 일회용 기기 연결, 접수·이력·통계·예외 조율 API.
- backend/app/flow_service.py: 지속 큐, 로컬 추론, 자동 예약·슬롯 분할, 상태 동기화·알림.
- backend/app/intent.py: 제한된 LLM 출력과 한국 시간 규칙 검증.
- backend/app/models.py: 새 테이블. 기존 DB에는 manage.py init-db로 추가.
- mobile/src/components/ElderMic.tsx: 단일 마이크, 수명주기, 접수 재시도와 음성 안내.
- mobile/src/components/FlowStaff.tsx: 대리 등록, 자동 배정 동의, 직원 업무함·통계·알림.
- mobile/src/device.ts: SecureStore와 기기 토큰 갱신.
- backend/tests/test_flow.py: 핵심 흐름·권한·재시작·중복·완료 회귀 검사.

## 검사 명령

backend 가상환경에서 `python -m pytest -q`.
mobile에서 `npm ci`, `npm run typecheck`, `npm test`.
번들은 `npx expo export --platform all --output-dir <임시 경로>`로 검사한다. 네이티브 기기 동작 검사는 별도다.

## 다음 검증

실기기와 로컬 모델·실제 지도 키로 FLOW-V2의 등록→접수→배정→거절→조율→수행 시나리오를 실행하고 측정한다. 푸시는 EAS 프로젝트와 플랫폼 자격증명 구성 뒤 검증한다. 모델 상주로 인한 메모리/속도 절충, 자동 안부 질문 재연결, 주소·담당자 변경 관리, 자연어 일정 변경 확장, receipt 확인과 다중 서버 처리는 남은 과제다.

## Windows에서 Codex로 열기

Git이 설치된 PC의 cmd에서, 아래 대상 폴더가 아직 없다면:

```bat
mkdir C:\dev
git clone https://github.com/ch041118/CLover.git C:\dev\CLover
```

이미 Git으로 복제한 폴더가 있으면 그 폴더를 사용한다. 기존 ZIP 폴더에는 git pull이 작동하지 않는다. Windows 앱에서 Codex를 선택하고 ‘프로젝트 추가’ 또는 Ctrl+O로 `C:\dev\CLover`를 연다. 프로젝트 파일을 옮긴다고 이 채팅 내용이 자동 이관되는 것은 아니므로 이 문서를 인계 기준으로 쓴다.

첫 요청 예시: “AGENTS.md와 docs/CODEX-HANDOFF.md, docs/FLOW-V2.md를 읽고 현재 구현을 확인한 뒤 실기기 검증을 도와줘. 기존 데이터와 암호화 키는 유지해줘.”

기존 backend/.env·DB·모델과 mobile/.env는 로컬에서 안전하게 옮긴다. .venv와 node_modules는 새 경로에서 다시 설치한다. .env, 암호화 키, 실제 돌봄 자료, 음성 파일을 Git에 올리지 않는다.

공식 참고: https://learn.chatgpt.com/docs/windows/windows-app
