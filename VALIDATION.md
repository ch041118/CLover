# 모바일 앱 전환 검증 (2026-09-19)

- 백엔드 기존 테스트: **69개 통과**. 추가한 모바일 가입 승인 권한 테스트: **1개 통과**.
- 모바일 API 테스트: **9개 통과** (HTTPS/개발망 예외, 인증 만료, 로그아웃 중 응답 폐기, 자동 재전송 금지).
- `npm run typecheck`: 통과.
- `npx expo export --platform android --platform ios`: 두 플랫폼 번들 생성 성공.
- 검증 환경: Python 3.12, Node.js 24.19, Expo SDK 57.
- 백엔드 테스트에서 의존성 deprecation 경고 2건이 발생했으며 테스트 실패는 없습니다.

실기기 설치·화면/접근성 점검, 실제 Ollama 추론, APK/IPA 서명 및 스토어 배포는 미수행입니다.
요양보호사 일정 배정과 다기관 격리는 아직 미구현입니다.

---

# v3 로컬 전용 버전 검증

- Python 3.12 `python -m pytest -q`: **69 passed**, 테스트 의존성 deprecation warning 2건.
- `python -m compileall -q backend`: 성공.
- 모델: qwen2.5:0.5b 고정. 실제 가중치는 패키지에 미포함.

## 확인한 동작

- 모든 개인 돌봄 데이터는 내부 처리. 신원/건강/경제/상담 보호 태그와 인증정보 차단 유지.
- 일반 안내문도 같은 로컬 모델·loopback endpoint를 사용.
- 애플리케이션 AST와 requirements에서 boto3/botocore/anthropic/openai 의존성이 없음을 확인.
- Bedrock/hybrid/외부 모드 설정 거부, 원격 URL·cloud 모델·다른 모델 설정 거부.
- proxy 환경변수 무시, 리다이렉트·과대 응답·도구 호출·비정상 JSON·불완전 응답·timeout 차단.
- 긴 입력은 잘라서 추론하지 않고 내부 호출 전에 차단, 원문은 기존 API를 통해 암호화 저장 가능.
- 공유 추론 슬롯이 사용 중이면 두 번째 요청은 호출 없이 검토 대기/오류 처리.
- 일반 안내문 JSON, local consent, 역할 접근 통제, 기존 외부 동의 필드 거부.
- 기존 가입/승인/권한/암호화/담당자 배정/안부/패턴 테스트 유지.

## 아직 확인하지 않은 범위

- 실제 Ollama 설치 및 qwen2.5:0.5b 다운로드/추론. 테스트에서는 HTTP 모의 응답을 사용.
- 사용자 PC의 실행 RAM, CPU/GPU 성능, 한국어 판단·문장 품질.
- 전체 Next.js 앱 빌드, 운영 DB·네트워크 방화벽, 장비 로그·백업 보호.

`python check_local.py`는 설치된 실제 모델에 합성 문장만 보내 분류와 안내문 출력 형식을 확인합니다. 통과하더라도 분류 정확도 인증은 아닙니다. 모든 결과는 담당자가 확인해야 합니다.
