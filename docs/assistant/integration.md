# SOLID-LLM AI 어시스턴트

## 역할과 API

- **규칙 기반 튜터**: FastAPI가 C/ASM/CRT 및 사이클 이벤트 해설을 생성한다. 외부 모델이 필요 없다.
- **AI 어시스턴트**: 로그인 사용자의 대화 텍스트를 SOLID-LLM으로 보내 기존 SSE로 답한다.
- **실행 컨텍스트 분석기**: 코드·전체 실행 결과·선택 사이클을 읽는 미래 모듈이다. `ExecutionContextProvider` 계약만 유지하며 구현·연결은 보류한다. 구현 시 소유권 검사가 필요하다.

[SOLID API 안내](https://dku-chat.kloud.zone/api-setup) 확인 기준:

- Base URL: `https://dku-chat.kloud.zone/llm/v1`
- `POST /chat/completions`, Bearer API key, OpenAI 호환 Chat Completions
- 기본 모델 `local/qwen3-coder-next`, `stream=true` 지원
- 계정 단위 월 한도. 키를 추가해도 한도는 늘지 않으며, 키를 폐기하면 즉시 접근이 차단된다.

OpenAI SDK를 사용하되 요청은 SOLID 주소로만 전송한다. OpenAI/Bedrock 자동 대체 호출은 없으며 boto3는 기존 S3 기능 때문에 유지한다.

## 설정

| 변수 | 기본값/의미 |
| --- | --- |
| ASSISTANT_ENABLED | false |
| ASSISTANT_PROVIDER | solid_llm |
| SOLID_LLM_BASE_URL | https://dku-chat.kloud.zone/llm/v1; 인증정보·query·fragment 없는 HTTPS |
| SOLID_LLM_MODEL | local/qwen3-coder-next |
| SOLID_LLM_API_KEY | 빈 값; 운영에서는 Secrets Manager 참조로 주입 |
| SOLID_LLM_INCLUDE_USAGE | true; 현재 gateway에서 검증. 명시적 환경값 false는 유지 |
| SOLID_LLM_CLASSIFICATION_FORMAT | json_schema; 현재 모델에서 검증, 미지원 gateway는 none으로 명시 |
| ASSISTANT_CLASSIFICATION_TIMEOUT_SECONDS | 10; 전체 요청 제한 시간 안에 포함 |
| ASSISTANT_MAX_TOKENS | 2048 (최대 4096) |
| ASSISTANT_TIMEOUT_SECONDS | 60 |
| ASSISTANT_DAILY_REQUESTS | 50 |
| ASSISTANT_COOLDOWN_SECONDS | 10 |

활성화 플래그를 켜도 키가 없거나 공백이면 provider를 만들지 않는다. 비활성/미설정 채팅은 로그인 검사 후 503 `AGENT_NOT_CONFIGURED`를 반환하며 사용량을 차감하지 않는다.

- `GET /api/v1/assistant/status`: 활성화 플래그와 키 설정 유무를 확인한다. 원격 모델 접근이나 월 잔여 한도를 보장하는 health probe가 아니다.
- `GET /api/v1/assistant/transport-check`: 고정 이벤트 2개를 0.5초 간격으로 반환한다. 사용자 입력·DB·외부 모델을 사용하지 않는다.
- `POST /api/v1/assistant/chat`: 기존 로그인 인증, `messages` 요청, `delta/done/error` SSE 형식을 유지한다.

## 스트리밍과 제한

OpenAI SDK AsyncOpenAI 및 비동기 HTTP로 전달한다. 워커당 최대 8개 upstream 호출, SDK 연결 5초/읽기 20초/전체 라우트 60초 제한이다. 모델 요청은 자동 재시도하지 않는다. 리다이렉트도 따르지 않아 인증정보가 다른 주소로 전달되지 않도록 한다. 완료·실패·취소 시 stream과 client를 닫는다.

사용자당 UTC 기준 50회/일, 요청 간 10초, 최대 20개 메시지, 각 8,000자·합계 24,000자 제한을 유지한다. 활성화된 모델 요청은 실패·취소해도 사용량에 포함된다. DB에는 대화 본문을 저장하지 않는다. 이 한도는 모든 사용자와 키가 공유하는 SOLID 계정 월 한도와 별개다.

- `delta.content`만 답변으로 전달하고 reasoning/tool 호출을 실행하거나 노출하지 않는다.
- `stop` → `end_turn`, `length` → `max_tokens`, `content_filter` → `content_filtered`.
- finish_reason 없이 연결 종료, 빈 응답, 잘못된 JSON, 지원하지 않는 도구 호출은 error다.
- role-only/usage-only 청크를 허용하고 usage가 없으면 `{}`를 전달한다. 0토큰으로 추정하지 않는다.
- 401/403 → MODEL_ACCESS_DENIED, 402 → MODEL_QUOTA_EXCEEDED, 429 → MODEL_BUSY, SDK timeout → MODEL_TIMEOUT.
- 공급자의 오류 본문·API 키·사용자 대화는 응답이나 로그에 출력하지 않는다.

## 비활성 배포 및 활성화 순서

1. 테스트·PR을 거쳐 앱만 비활성 상태로 먼저 배포하고 status/CORS/SSE/기존 튜터를 검증한다. DB 변경은 없다.
2. SOLID에서 전용 키를 발급하고 계정 `242925688392` / 서울의 Secrets Manager에 JSON `api_key` 필드로 등록한다. 값은 채팅·Git·명령 인자·출력에 남기지 않는다. 이 문서에는 실제 키가 없다.
3. 기존 runtime 스택의 SecretKey로 암호화한 secret ARN을 `SolidLlmApiKeySecretArn`으로 runtime/environment 템플릿에 전달한다. 값이 빈 문자열이면 추가 권한·환경 참조를 만들지 않는다. 다른 KMS 키를 사용하려면 해당 키에 대한 최소 복호화 권한도 별도로 검토한다.
4. 인프라 검증·변경 세트를 확인하고 runtime 권한을 먼저, environment 참조를 나중에 적용한다. **환경 스택 업데이트마다 `DescribeEnvironments`의 현재 `VersionLabel`을 `ExistingApplicationVersion`에 명시한다.** CI가 별도로 앱을 배포하므로 이전 매개변수 값을 재사용하면 안 된다. 신규 환경은 이 값을 비워 초기 `Version`을 사용한다. 이번 비활성 앱 배포는 이 스택 변경을 자동 실행하지 않는다.
5. Beanstalk의 `SOLID_LLM_API_KEY`는 `aws:elasticbeanstalk:application:environmentsecrets`에서 `secret ARN:api_key`로 참조한다. 키는 플랫폼이 런타임에 해석한다. 키 변경 후에는 환경 갱신/앱 재시작이 필요하다.
6. 프로젝트 비밀값 작업 규칙에 따라 로컬 검증에는 `asm-exec`와 `{{resolve:secretsmanager:secret-id:SecretString:api_key}}` 참조를 사용한다. 비밀값 읽기 API를 직접 호출하거나 환경 전체를 출력하지 않는다.
7. 서울 서버에서 소량의 비스트리밍·스트리밍 요청으로 인증, 모델 접근, `max_tokens`, 한국어, usage 옵션 호환성을 확인한다. 성공하기 전에는 실제 서비스 응답 검증 완료로 표시하지 않는다.
8. `AssistantEnabled=true` 후 로그인한 실제 채팅의 응답·취소·한도를 확인한다. 프론트 배포는 별도 담당자가 진행한다.

키 생성/저장/인프라 적용/실제 모델 호출은 완료 여부를 PR 검증 기록에서 별도로 확인한다. mock 테스트나 고정 SSE 진단은 실제 모델 성공을 의미하지 않는다.

## 롤백과 운영

문제가 생기면 ASSISTANT_ENABLED=false로 되돌린다. 사용량 테이블과 규칙 튜터는 그대로 유지한다. 외부 계정 키를 폐기했다면 환경 참조도 갱신한다. Bedrock으로 자동 복귀하지 않는다. 사용자에게 자체 로그인 오류와 공급자 계정 한도/키 오류를 구분해 안내한다.

[프론트 인수인계](frontend-handoff.md) · [AWS environmentsecrets와 JSON key extraction](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/AWSHowTo.secrets.env-vars.html) · [OpenAI Python SDK](https://developers.openai.com/api/reference/python)

## 서울 운영 연결 검증 (2026-11-11)

- SOLID 전용 키는 운영자가 콘솔에 직접 등록했다. 이번 연결은 승인된 예외에 따라 Beanstalk 기본 비밀 참조로 주입했으며, 검증 도구가 Secrets Manager 비밀값을 직접 읽지 않았다.
- `runtime` 변경 세트는 `InstanceRole`의 기존 읽기 정책에 전용 secret ARN 하나만 추가한다. 환경 업데이트는 현재 앱 버전을 명시해 초기 앱으로 되돌아가지 않게 했다. DB·네트워크·기존 비밀은 변경하지 않는다.
- cfn-lint 1.60.0: 두 템플릿 오류·경고 0. cfn-guard 3.2.1: AWS 공식 규칙 중 KMS 회전, KMS principal, CMK 사용, IAM trust/권한의 5개 검사 통과. 이는 전체 계정 보안 감사 결과가 아니다. CMK 규칙의 intrinsic 비교 경고는 실제 secret의 KMS ARN을 별도 확인했다.
- CloudFormation 변경 세트 생성과 `DescribeEvents` 사전 검증 통과, 리소스 교체·삭제 없음. 장기 CloudTrail trail은 기존 구성대로 별도 추가하지 않았다.
- 서울 앱 컨테이너에서 일반 응답, 기본 스트리밍, `stream_options.include_usage=true` 모두 성공했다. 한국어 delta와 정상 종료를 확인했고, 64토큰 제한에서는 `max_tokens` 종료도 확인했다. usage 옵션은 지원되지만 운영 기본값은 계속 false다.

- 활성화 변경 세트까지 `UPDATE_COMPLETE`, Beanstalk `Ready/Green/Ok`, 앱 버전 유지 확인. 공개 status는 `ENABLED`, health 200, CORS preflight 200, 미인증 chat 403, 고정 SSE 두 이벤트 간격 0.495초를 확인했다. 로그인 사용자의 공개 채팅·한도 검증은 아래 2026-11-12 기록을 따른다. 프론트는 미배포다.


## 로그인 채팅 최종 검증 (2026-11-12)

사용자 승인하에 격리된 임시 계정 1개를 만들고 공개 API로 검증했다. 실제 사용자 데이터는 변경하지 않았다.

- `/auth/login` 200, Bearer 인증 `/api/v1/assistant/chat` 200 / `text/event-stream`.
- SOLID 실제 호출 1회: 한글 delta 52개, 첫 delta 0.801초, 전체 1.121초, `done.end_turn`, 오류 이벤트 없음. 이는 단일 요청 관측값이며 성능 보장 수치가 아니다.
- 사용량 1회 기록을 확인한 후 해당 임시 계정의 횟수만 일일 한도로 설정해 추가 모델 호출 없이 429 `ASSISTANT_RATE_LIMIT`을 확인했다.
- 검증 후 임시 사용자와 해당 사용량 기록을 삭제했다. 재조회 결과 두 테이블 모두 해당 테스트 ID의 행은 0개였다.
- API 키, 임시 비밀번호, 로그인 토큰, 실제 사용자 정보는 검증 출력에 기록하지 않았다.
- 프론트 배포는 계속 보류하며 실행 컨텍스트 분석기는 미연결이다.


## 주제 판별 도메인 제한 (구현 완료 후 별도 배포 필요)

인증·요청 한도 예약 뒤 SOLID 주제 판별을 수행하고 ALLOW일 때만 답변을 생성한다.
범위 밖·확인 요청·인사는 고정 delta → done, 판별 장애는 기존 error 이벤트로 반환한다.
요청당 quota 1회, 기존 messages/SSE 계약을 유지하며 원문 로깅·자동 실행 맥락 조회를 추가하지 않는다.
세부 정책·설정·사용량 합산·검증 한계는 [도메인 제한 문서](domain-policy.md)를 참조한다.
이 변경은 운영 미배포이며, 위 11월 11~12일 기존 연결 검증과 구분해야 한다.
