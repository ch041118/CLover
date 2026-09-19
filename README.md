# CLover — 로컬 AI 기반 안부 케어 앱

**Android·iPhone 앱 + 기관 PC의 로컬 AI 서버 구성입니다.** 모바일 실행 순서는 [앱 개발 안내](docs/MOBILE.md)를 참고하세요. 로그인·가입 승인·안부·돌봄 접수·담당자 검토·안내문 화면을 제공합니다.

**기본 모델: `qwen2.5:0.5b` (Ollama, Q4_K_M)**

이전 버전의 Bedrock 코드·AWS SDK·AWS 설정·Terraform 파일을 제거했습니다. 돌봄 요청 분류와 일반 안내문 작성 모두 같은 컴퓨터의 로컬 모델을 사용합니다. API 키·AWS 계정·클라우드 요금은 필요하지 않습니다. 초기 설치와 모델 다운로드에는 인터넷이 필요합니다.

## 모델 선택 이유와 한계

[공식 모델 페이지](https://ollama.com/library/qwen2.5:0.5b) 기준 약 494M 파라미터, 다운로드 약 **398MB**입니다. 한국어를 포함한 다국어 지원이 있고 비교한 Qwen3 0.6B(약 523MB)보다 다운로드가 작아, 이번 요청의 가벼운 실행을 우선해 선택했습니다. 세상에서 가장 작은 모델이라는 뜻은 아닙니다.

398MB는 다운로드 크기이며 실행 메모리 총량이 아닙니다. Python·Ollama·KV cache·OS 메모리는 별도로 필요합니다. CPU로 실행할 수 있지만 사용자 PC의 속도와 메모리 사용량은 아직 측정하지 않았습니다. 작은 모델이므로 한국어 이해·판단·문장 품질이 큰 모델보다 제한될 수 있습니다. 임상적으로 검증된 분류기가 아니며 모든 결과는 담당자가 최종 확인합니다.

## 가볍게 실행하도록 변경한 점

- 모델 하나를 고정 사용: `qwen2.5:0.5b`.
- 컨텍스트 2,048 토큰, 분류 출력 최대 128 토큰, 안내문 최대 192 토큰.
- 앱에서 동시 추론 1건. Ollama도 모델 1개·병렬 추론 1개로 제한.
- 요청 후 `keep_alive=0`으로 모델 언로드 요청. 메모리를 줄이는 대신 다음 요청의 로딩 시간이 늘 수 있음.
- 전체 프롬프트 UTF-8 1,400바이트를 넘으면 잘라 읽지 않고 `local_input_too_long`으로 담당자 확인. 한국어 원문은 보통 수백 자 이내가 대상이며 정확한 한도는 선택 항목과 문자 구성에 따라 달라짐.
- 서버의 원문 저장 한도는 기존 4,000자 유지. 긴 요청은 그대로 암호화 저장되고 AI만 생략.
- 모델 오류·바쁨·시간 초과·잘못된 출력은 검토 대기. 다른 모델이나 외부 API 호출 없음.

## Windows 신규 설치 순서

Python 3.11 이상과 [Ollama Windows](https://ollama.com/download/windows)를 설치합니다. 모델 설치는 실제 개인정보를 넣기 전에 완료하세요.

**1. cmd에서 모델을 한 번 다운로드**

```bat
ollama pull qwen2.5:0.5b
```

다운로드가 끝나면 작업표시줄의 Ollama 아이콘에서 Quit로 종료합니다. 이후 전용 실행 스크립트로 cloud 기능을 끈 서버를 실행합니다.

**2. 저장소의 `backend`에서 Python 환경 준비**

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python setup_env.py
```

`setup_env.py`는 안전한 JWT 키와 데이터 암호화 키를 만들어 `.env`에 저장합니다. 기존 파일은 덮어쓰지 않습니다. DATA_KEY를 안전하게 백업하세요. 잃어버리면 기존 요청 원문을 복호화할 수 없습니다.

**3. `.env`의 아래 네 항목 확인/수정**

```dotenv
LLM_MODE=local
LOCAL_MODEL=qwen2.5:0.5b
LOCAL_MODEL_URL=http://127.0.0.1:11434
LOCAL_PRIVACY_REVIEWED=true
```

`LOCAL_PRIVACY_REVIEWED`는 전용 실행 스크립트, 클라우드 차단과 기관의 로컬 보안을 확인했다는 표시이며 방화벽 자동 설정 기능은 아닙니다. 나머지 JWT_SECRET/DATA_KEY 값은 그대로 둡니다. AI를 잠시 끄려면 `LLM_MODE=disabled`를 사용합니다.

**4. DB와 관리자 생성 (최초 한 번)**

```bat
python manage.py init-db
python manage.py create-admin
```

기본 관리자 비밀번호는 없습니다. 직접 정한 ID와 비밀번호를 입력하세요.

**5. 첫 번째 cmd에서 로컬 모델 서버 실행**

```bat
python start_local_model.py
```

이 창을 유지합니다. 이미 11434 포트가 사용 중이면 스크립트가 중단됩니다. 기존 Ollama 앱/서비스를 종료한 후 다시 실행하세요. 이 스크립트는 `OLLAMA_NO_CLOUD=1`, `OLLAMA_HOST=127.0.0.1:11434`, 모델·병렬 수 제한을 적용합니다. 백엔드 `.env`만 수정해서는 이미 실행 중인 Ollama 설정이 바뀌지 않습니다.

**6. 두 번째 cmd에서 백엔드 실행**

같은 backend 폴더로 이동합니다.

```bat
.venv\Scripts\activate
python check_local.py
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log --workers 1
```

`check_local.py`는 가상 문장으로 실제 로컬 분류·안내문 생성을 확인합니다. 정확도 검증은 아닙니다. 분류 실패/시간 초과 시 클라우드로 우회하지 않습니다.

브라우저에서 `http://localhost:8000/docs`에 접속합니다. Swagger는 개발용 API 화면입니다. 완성된 사용자 웹사이트가 아닙니다.

## 기존 v1/v2 사용자가 업데이트할 때

1. 기존 서버를 종료하고 소스 폴더와 DB를 백업합니다.
2. 새 패키지를 별도 폴더에 풉니다. 기존 `.env`와 `care.db`는 기존 암호화 키를 유지하여 가져옵니다. 임의로 새 DATA_KEY를 만들지 마세요.
3. 의존성을 다시 설치하고 위의 네 로컬 설정을 적용합니다. 기존 `bedrock`/`hybrid` 모드는 더 이상 허용되지 않습니다.
4. 기존 `.env`와 실행 환경의 AWS 인증키·Bedrock 설정은 제거하세요. 이 앱은 사용하지 않습니다. 기존에 만든 AWS 리소스의 비용 청구는 코드 변경으로 중단되지 않으므로 불필요한 리소스는 AWS에서 별도로 정리해야 합니다.
5. DB 컬럼은 변경하지 않았습니다. v1/v2 저장 데이터는 그대로 열 수 있고, 과거 요청을 재추론/외부 전송하지 않습니다. 새 요청부터 `care-local-v3` 정책 메타데이터가 암호화 저장됩니다.

## API 사용

회원가입 → 관리자 로그인 → 승인 → 어르신 로그인 → 요청 접수 → 사회복지사 로그인 → 담당 접수 → 내용 확인/수동 분류 순서입니다. Swagger Authorize에는 JWT의 access_token 값만 붙여 넣습니다.

돌봄 요청 `POST /api/care-requests`:

```json
{
  "note": "오늘 식사를 준비하기 어려워요.",
  "features": {
    "category": "meal",
    "signals": ["missed_meal"],
    "duration": "today",
    "can_self_manage": false
  },
  "allow_local_ai": true
}
```

`allow_local_ai=false`여도 접수되며 사람이 확인합니다. 과거 `allow_structured_ai` 필드는 호환 목적으로 받되 무시하며 동의로 재사용하지 않습니다. 긴급 키워드와 선택 항목은 모델 없이 우선 확인합니다.

일반 안내문 `POST /api/general-drafts` (관리자·사회복지사 전용):

```json
{"topic":"welcome_notice","allow_local_ai":true}
```

주제: `welcome_notice`, `volunteer_etiquette`, `service_introduction`. 이전의 `allow_external_ai` 필드는 제거됐으며 입력하면 422로 거부됩니다. 일반 안내문도 동일한 로컬 모델을 사용하고 결과는 텍스트로 표시한 뒤 사람이 검토하세요.

`frontend/CareRequestForm.tsx`는 기존 Next.js 앱에 넣는 요청 폼입니다. 완성된 Next.js 프로젝트나 역할별 대시보드는 포함하지 않습니다.

## 보안과 기능 범위

- 개인정보/건강/복약/경제/가족·상담 정보 태그를 서버에서 분류하되 모든 내용은 로컬 처리. 탐지되지 않은 내용도 외부 모델로 가지 않음.
- 감지된 인증키·비밀번호는 저장과 모델 입력을 거부. 탐지는 완벽하지 않으므로 비밀키를 입력하지 마세요.
- 흔한 전화·이메일·주민번호 패턴은 내부 추론 전에도 제거. 모든 실명/주소를 비식별화한다는 보장은 없음.
- loopback 주소만 허용. 환경 HTTP 프록시 무시, 리다이렉트·도구 호출·cloud 모델 금지.
- 실제 네트워크 격리를 위해 다운로드 후 Ollama 프로세스의 인터넷 송신을 방화벽으로 막으세요. cloud-off와 주소 검사만으로 장비 전체의 정보 유출 0%를 보장하지 않음.
- 백엔드·DB·모델 모두 기관 내 PC/서버에 두어야 기관 내부 처리입니다. 외부 서버에 설치하면 데이터 처리 장소도 외부가 됨.
- 회원 승인, 역할/담당자별 접근 제어, 원문 Fernet 암호화, 최소 감사 기록, 일일 안부 체크, 최근 반복 요청 집계 유지.
- 운영에는 TLS·접근 통제·속도 제한·DB/백업 보호 필요. 모델 신뢰도 수치는 실제 정확도 보장이 아님.
- 응급 모델이 아니며 119 자동 신고 기능 없음. 담당자가 요청을 확인하는 절차 필요.
- 다기관 격리, 보호자 대리 관계, 요양보호사 일정·평점 매칭, 요양보호사 일정 화면은 아직 미구현.

## 테스트

```bat
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

자동 테스트 결과와 실제 모델 검증 여부는 `VALIDATION.md`를 참고하세요. 모델 파일은 압축에 포함하지 않았습니다.

## 공식 자료

- [Qwen2.5 0.5B 모델](https://ollama.com/library/qwen2.5:0.5b)
- [Ollama Windows](https://docs.ollama.com/windows)
- [Ollama cloud 기능 끄기](https://docs.ollama.com/faq)
- [Ollama Chat API](https://docs.ollama.com/api/chat)
