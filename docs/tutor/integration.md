# FastAPI 규칙 기반 튜터 이전

## 구현 범위

- `POST /api/v1/tutor/explain`: 컴파일 전 C 줄과 ASM/CRT 해설. `items` 순서대로 응답한다.
- `POST /api/v1/build/compile`: 기존 응답을 유지하고 RV32IM 성공 시 `tutor`를 추가한다. native/실패 시 null.
- `POST /api/v1/simulation/run`: 기존 CORE `result`를 유지하고 바깥에 `tutor`를 추가한다. CORE 계약은 변경하지 않는다.
- 프런트는 컴파일·실행 응답의 해설을 캐시하고 C 줄 선택 시 누락 항목만 요청한다. 재생 중에는 사이클별 해설을 응답에서 조회한다.
- `POST /api/v1/assistant/chat`: 로그인한 사용자의 텍스트 대화를 Bedrock Sonnet으로 전송하고 SSE로 답한다. 기본값은 비활성화이며, 활성화 전에는 503 `AGENT_NOT_CONFIGURED`를 반환한다. 계정의 모델 이용 권한이 아직 없어 실제 성공 응답은 검증하지 못했다.
- 전체 실행 저장·자동 맥락 조회·AI 실행 분석은 보류. `ContextProvider`는 추후 구현자가 소유권 검사 후 연결하는 인터페이스다.

## 해설 API

```json
{"items":[{"kind":"c","text":"int x = 2;","line":3},{"kind":"asm","text":"lw a0, 0(a1)"},{"kind":"crt","text":"auipc ra, 0","pc":"0x10000"}]}
```

`kind`: c/asm/crt. 항목당 4,096자, 요청당 1~128개, 줄 번호 1 이상. 무료 정적 규칙 처리로 DB 및 외부 모델을 호출하지 않는다. 외부로 공개할 때 기존 게이트웨이 요청 제한 정책을 적용한다.

응답은 `schema_version: "1.0"`, `items`이며 항목은 `kind/category/title/summary/detail/opcode/operands`를 제공한다. CSS 색상은 프런트에서 지정한다. 단일 줄 패턴 분석이므로 C 전체 문법·스코프·실제 최적화 결과를 판정하지 않는다.

## 빌드 응답

`tutor`는 `schema_version`, `source_sha256`(실제 컴파일 소스), `c_lines`, `asm_instructions`를 포함한다. 각 항목은 원본 `text`, 1부터 시작하는 `line`, `explanation`을 갖는다. 빌드 단계에서는 아직 PC가 없어 ASM 원본 줄로 연결한다. 실제 PC 및 런타임 매핑은 시뮬레이션 결과에서 보완한다. 해설 규칙에 사용하는 텍스트는 줄당 4,096자로 제한한다.

## 시뮬레이션 응답

`tutor.asm_instructions`는 PC, 원본 명령어, source_line, 일반 명령어 해설, 선택적 runtime_explanation을 제공한다. 소스 줄이 없는 매핑은 기존 프런트의 런타임 구분을 따르지만 실제 main 호출 여부는 단정하지 않는다.

`tutor.cycle_explanations`는 이벤트가 있는 사이클만 포함한다.

- `history_index`: 원본 history의 0부터 시작하는 인덱스
- `cycle`: CORE clock 값. 인덱스와 동일하다고 가정하지 않는다.
- `events`: 스톨/포워딩/플러시를 우선순위로 하나만 고르지 않고 모두 반환
- 이벤트마다 `type/title/summary/detail/evidence` 제공
- `evidence`는 해당 CORE 이벤트다. 원인이 없으면 부족함을 명시하고 특정 레지스터·스톨 횟수를 추측하지 않는다.
- `control_hazard_branch_taken`은 분기 또는 점프에 따른 제어 흐름 변경으로 설명한다. 분기 예측 실패라고 단정하지 않는다.

## 프런트 작업 복제본과 패치

FE main `82a9a341f91780a37e9a793c96a30c13b569ceed`를 기반으로 `dist/FE`에 변경했다. 이 경로는 BE Git에서 제외되므로 재현 가능한 변경을 `patches/tutor-frontend.patch`에도 보관한다. FE 저장소에서 `git apply <BE 경로>/patches/tutor-frontend.patch`로 적용 가능하다. BE를 먼저 배포한 뒤 FE를 반영해야 한다. 아직 양쪽 모두 커밋·푸시·배포하지 않았다.

## Bedrock Sonnet 연결

```text
채팅 화면 → FastAPI /api/v1/assistant/chat → Bedrock ConverseStream (서울)
              ├─ 기존 로그인 검사
              ├─ DB에서 사용자별 요청 한도 예약
              └─ SSE delta / done / error → 채팅 화면
```

- 모델: `anthropic.claude-sonnet-5`, 리전: `ap-northeast-2`. 최신 모델 자동 선택이나 다른 리전으로의 자동 전환은 없다.
- 인증: 배포 시 EC2 인스턴스 역할. 로컬 실행은 `AWS_PROFILE=archreactor-new`를 명시한다. AWS 키를 프런트로 전달하지 않는다. `aws login` 프로파일을 지원하도록 `boto3[crt]==1.43.126`으로 갱신했다.
- 기본 제한: 사용자당 UTC 날짜 기준 50회/일(한국시간 오전 9시 초기화), 요청 간 10초, 최근 최대 20개 메시지, 메시지당 8,000자, 합계 24,000자, 출력 2,048토큰, 전체 응답 60초. 한도는 설정에서 변경 가능하다.
- `assistant_usage` 테이블의 원자적 upsert로 여러 워커/인스턴스와 재시작 사이에도 요청 한도를 공유한다. 실패/취소 요청도 횟수에 포함한다. 대화 본문은 이 테이블에 저장하지 않는다. 금액 기준의 계정 전체 예산 제한은 별도로 필요하다.
- SDK 호출은 워커당 최대 8개 스레드로 제한하고, 유한 큐로 느린 클라이언트의 메모리 증가를 막는다. SDK 연결 제한 5초/읽기 제한 20초/최대 2회 시도. 브라우저 중단·닫기·연결 끊김 시 upstream 스트림을 닫는다. 아직 연결 중이면 반환 직후 닫으며 실행 슬롯은 실제 SDK 호출 종료까지 유지한다. 취소가 이미 발생한 모델 비용을 되돌리지는 않는다.
- 10초마다 SSE keepalive, `Cache-Control: no-cache, no-store`, `X-Accel-Buffering: no`를 전송한다. 운영 프록시와 CloudFront를 경유한 스트리밍 검증은 배포 후 수행해야 한다.
- SSE `data` JSON: `{type:"delta",text:"..."}`, `{type:"done",stop_reason:"end_turn",usage:{inputTokens,outputTokens,totalTokens}}`, `{type:"error",code:"MODEL_ACCESS_DENIED",message:"..."}`. 스트림 개시 전에는 HTTP 인증/검증/한도 오류를 반환하고, 개시 후 모델 오류는 HTTP 200 스트림 안의 error 이벤트로 전달한다.
- 사용자가 직접 보낸 텍스트만 전달한다. 화면/전체 실행/소스 자동 수집과 도구 실행은 제공하지 않는다. 프런트 안내 및 시스템 프롬프트에도 이 범위를 명시한다.

### 활성화 순서와 현재 상태

1. AWS 계정 `242925688392`, 서울 리전에서 Sonnet 모델 이용 권한을 확보한다. 2026-11-09 STS 계정 확인 후 호출했지만 AWS가 `AccessDeniedException`과 `anthropic.claude-sonnet-5 is not available for this account`를 반환했다. 조회 결과 지역 지원/authorization/entitlement는 AVAILABLE/AUTHORIZED였으나 agreement는 NOT_AVAILABLE이었다. AWS 응답은 추가 접근 옵션을 위해 AWS Sales 문의를 안내했다.
2. `infrastructure/runtime.yml`의 인스턴스 역할에 해당 서울 모델의 `bedrock:InvokeModelWithResponseStream` 권한을 적용한다. 다른 모델/리전/관리 API 권한은 추가하지 않는다.
3. BE 배포 시 `e7a124b891c0` 마이그레이션을 적용한다. 기존 테이블 변경 없이 사용량 테이블을 추가한다.
4. `infrastructure/environment.yml`의 `AssistantEnabled=true`로 활성화한다. 기본값은 false다.
5. FE 패치를 적용·배포하고 로그인 후 정상 응답/중단/한도/프록시 경유 실시간 표시를 확인한다.

현재 로컬 구현과 테스트를 완료했으며 IAM 변경, 운영 DB 변경, 활성화, BE/FE 배포는 수행하지 않았다. 모델 계정 권한 문제 때문에 실제 Sonnet 답변 성공은 확인되지 않았다.

## 보류한 KloudChat 연결

공식 문서: https://boanlab.github.io/KloudChat/docs/api

기관이 운영하는 KloudChat의 계정 메뉴 → API 연동 화면에 실제 서비스 URL과 모델 ID를 사용한 예제가 있다. 문서 사이트는 모델 서버가 아니다. 로그인 주소를 모르면 기관 운영자에게 요청한다. API 키는 해당 KloudChat 설정 → API 키에서 발급한다. 이 작업에서 키를 발급하거나 읽지 않았다.

모델 게이트웨이 기준 주소는 `https://<실제 서비스 주소>/llm/v1`, 채팅은 `/chat/completions`, 모델 목록은 `/models`다. 스트리밍을 지원한다. 이 경로는 KloudChat의 프로젝트·도구·에이전트 실행 전체를 자동 제공하는 것과 다르다. KloudChat으로 전환할 때는 실제 URL·허용 모델·인증 보관 방식을 정한 뒤 기존 SSE 라우트에 새 AgentProvider를 연결한다.

서버 URL과 키를 프런트 입력으로 받아 임의 외부 URL로 전달하지 않는다. 별도 서버 설정으로 고정하고, 공개 채팅 활성화 전에 인증·요청 제한·출력 제한·시간 제한·연결 취소·비밀값 마스킹을 구현한다.

## 검증

- PostgreSQL 임시 DB에서 전체 BE 테스트: 83개 통과, RISC-V 크로스 컴파일러가 필요한 1개 생략. 마이그레이션과 20개 동시 요청 중 허용된 5개만 성공하는 제한도 검증했다.
- FE TypeScript/Vite 빌드 성공. `node --test tests/assistant.test.mjs`: 한글 UTF-8 분할, SSE 프레임/오류/연결 끊김, 대화 크기 제한 4개 통과.
- CloudFormation `validate-template`: runtime/environment 통과. 로컬 cfn-lint/cfn-guard가 없어 해당 검사 및 배포 전 change set 검증은 수행하지 않았다.
- SDK 모의 테스트: 텍스트/토큰 사용량 전달, 권한 오류 마스킹, 생성 중 취소 및 연결 지연 중 취소 시 upstream 닫기.
