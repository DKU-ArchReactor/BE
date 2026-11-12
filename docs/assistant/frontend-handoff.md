# 프론트 인수인계: 규칙 기반 튜터와 AI 어시스턴트

> 후속 백엔드 PR의 선택 실행 맥락 계약은 [실행 맥락 인수인계](execution-context-handoff.md)를 참고한다. 아직 새 PR 배포/프론트 반영 전이며, 아래 기존 메시지 전용 계약도 유지된다. 전체 실행 자동 조회는 계속 보류다.

## 반영 상태와 순서

- 튜터 BE PR: https://github.com/DKU-ArchReactor/BE/pull/3 (병합됨). 튜터 FE PR: https://github.com/DKU-ArchReactor/FE/pull/18 (미병합).
- 이번 작업에서 프론트 PR 병합·배포는 하지 않는다. 기존 프론트 배포 계정/버킷은 백엔드 계정과 다르므로 담당자가 배포 대상을 확인해야 한다.
- 백엔드 기준 URL: `https://d1j3nkcez6kncs.cloudfront.net`. `VITE_API_URL`에 지정한다.
- 이름: **규칙 기반 튜터**(학습 해설), **AI 어시스턴트**(대화), **실행 컨텍스트 분석기**(향후 전체 실행 맥락 구성). 실행 컨텍스트 분석기는 아직 연결되지 않았다.

## 1. 규칙 기반 튜터

FE PR #18을 먼저 검토한다. 컴파일 응답과 시뮬레이션 응답의 바깥 `tutor` 필드를 보존한다. 시뮬레이션의 `result`만 추출하며 `tutor`를 버리지 않도록 주의한다.

- `tutor.c_lines`: C 줄별 해설. 원본 줄 번호는 1부터 시작한다.
- `tutor.asm_instructions`: 명령어/선택적 CRT 해설. 컴파일 단계에서는 ASM 텍스트가 없을 수 있으므로 시뮬레이션 코드 매핑을 사용한다.
- `tutor.cycle_explanations`: 이벤트가 있는 사이클만 담는다. `cycle`은 CORE clock, `history_index`는 원본 이력의 0부터 시작하는 위치다. 한 사이클의 stall/forwarding/flush를 모두 표시한다.
- 캐시가 없거나 컴파일 전 C 줄을 선택하면 `POST /api/v1/tutor/explain`에 `{ "items": [{ "kind": "c", "text": "int x = 2;", "line": 1 }] }`를 전송한다. 항목은 최대 128개, text는 최대 4,096자다.
- 해설 규칙은 프론트에 중복 구현하지 않는다. 서버의 title/summary/detail을 표시하고 색상·레이아웃만 프론트가 처리한다.

## 2. AI 어시스턴트 준비 상태

2026-11-11 서울 백엔드 활성화 완료: 현재 응답은 `{"enabled":true,"code":"ENABLED"}`다. SOLID 실제 일반·한국어 스트리밍 호출과 공개 API의 CORS/미인증 차단/고정 SSE를 확인했다. 2026-11-12 임시 계정으로 실제 로그인 → 공개 채팅 SSE 정상 종료와 일일 한도 429까지 검증했고 테스트 데이터는 삭제했다. 프론트는 여전히 미배포이며, 아래 비활성 응답도 계속 처리해야 한다.

`GET /api/v1/assistant/status` 응답:

```json
{"enabled":false,"code":"AGENT_NOT_CONFIGURED"}
```

false일 때 입력/전송을 비활성화하고 ‘AI 어시스턴트 연결 준비 중’ 안내를 보여준다. 이 값은 활성화 플래그와 키 설정 유무를 확인하며, true만으로 실제 SOLID 모델 접근 성공을 보장하지는 않는다. API 키 입력 UI는 만들지 않는다.

## 3. 채팅 계약

`POST /api/v1/assistant/chat`

```http
Authorization: Bearer <기존 로그인 access_token>
Content-Type: application/json
Accept: text/event-stream
```

```json
{"messages":[{"role":"user","content":"load-use 스톨이 뭐야?"}]}
```

role은 user/assistant만 허용하며 첫/마지막 메시지는 user다. 최대 20개, 메시지당 8,000자, 합계 24,000자다. 전체 화면·코드·실행 이력을 자동으로 전송하는 기능은 없다.

SSE `data:` JSON 이벤트:

```text
data: {"type":"delta","text":"스톨은..."}

data: {"type":"done","stop_reason":"end_turn","usage":{"inputTokens":10,"outputTokens":20,"totalTokens":30}}

data: {"type":"error","code":"MODEL_ACCESS_DENIED","message":"..."}
```

- POST+Bearer 인증이 필요하므로 `fetch`의 스트림을 사용한다. TextDecoder의 streaming 모드로 UTF-8 한글과 분할 프레임을 처리한다.
- `: connected`, `: keepalive`는 주석으로 무시한다. done 전 연결이 끝나면 완료로 표시하지 않는다.
- 전송 중 중복 요청을 막고 중단 버튼·팝업 닫기에서 AbortController를 호출한다.
- 실패한 답변/안내 문구는 다음 대화 이력에 넣지 않는다.
- 출력 제한으로 `stop_reason=max_tokens`이면 응답이 잘렸다는 안내가 필요하다.
- 스트림 시작 전: 401/403 로그인 오류, 422 요청 검증, 429 사용량 제한, 503 비활성. 시작 후 실패는 HTTP 200 SSE 안의 error 이벤트로 전달된다.
- 기본 제한: UTC 날짜 기준 50회/일(한국시간 오전 9시 초기화), 요청 간 10초, 출력 2,048토큰, 전체 60초. 활성화된 요청은 실패·취소해도 횟수가 차감된다. 비활성 요청은 차감하지 않는다.

## 4. 모델 없는 통신 확인

`GET /api/v1/assistant/transport-check`는 고정된 `diagnostic`/`done` 이벤트 두 개를 0.5초 간격으로 보낸다. 모델을 호출하지 않으며 실제 채팅 UI의 답변으로 사용하지 않는다. HTTPS·CORS·프록시 버퍼링 검증용이다.

## 5. 인수 테스트

1. 튜터: 컴파일 전 C 줄 선택, C/ASM 컴파일, single/pipeline 실행, 같은 사이클의 복수 이벤트 표시.
2. 비활성 채팅: 준비 중 안내, 전송 차단, 로그인 및 503 처리.
3. 승인 후 채팅: 한글 스트리밍, 중단/닫기, 429, 시간 초과, 연결 끊김, max_tokens 표시.
4. 화면/실행 결과를 자동으로 읽는다는 안내나 동작을 추가하지 않는다. 실행 컨텍스트 분석기 연동은 후속 범위다.

별도 프론트 채팅 준비 초안은 미배포 상태다. 담당자는 위 계약을 기준으로 상태 조회·준비 중 표시를 보완해야 한다. 이번 백엔드 배포에는 프론트 변경이 포함되지 않는다.

## SOLID-LLM 전환 인수인계

- 백엔드 공급자를 SOLID-LLM으로 변경한다. 기본 모델은 `local/qwen3-coder-next`다.
- 프론트 API 주소, 기존 로그인 인증, `delta/done/error` SSE 계약은 유지한다. SOLID API를 브라우저에서 직접 호출하지 않는다.
- API 키가 없으면 `ASSISTANT_ENABLED=true`여도 status는 false이고 로그인된 chat은 503이다.
- SOLID `length` 종료는 기존 `stop_reason=max_tokens`로 변환한다. `content_filtered`이면 제한 안내를 표시한다.
- `usage`가 빈 객체이면 사용량 정보 미제공이다. 토큰 사용량을 0으로 표시하지 않는다.
- `MODEL_ACCESS_DENIED`: 서비스 인증/권한 문제, `MODEL_QUOTA_EXCEEDED`: 서비스 계정 한도/결제 확인, `MODEL_BUSY`: 요청 제한 또는 월 한도, `MODEL_CONTENT_FILTERED`: 응답 제한이다. 사용자의 ArchReactor 로그인 만료와 구분한다.
- SOLID 계정 월 한도는 모든 앱 사용자가 공유한다. 앱 사용자별 50회/일 제한과 별도다.
- 실행 컨텍스트 분석기는 여전히 미연결이다. 코드·화면·실행 이력을 자동으로 읽는다고 안내하지 않는다.


## 추가 인수인계: 주제 판별 도메인 제한 (운영 미배포)

백엔드 구현만 추가했으며 프론트 작업·배포 보류를 유지한다.

- 기존 `POST /api/v1/assistant/chat`의 `messages`와 인증 헤더를 그대로 사용한다. 별도 판별 요청은 필요 없다.
- 허용 질문은 기존 스트리밍 답변, 범위 밖·확인 요청·인사는 서버 고정 `delta → done`이다. 동일하게 표시하면 된다.
- 새 `error.code=CLASSIFICATION_UNAVAILABLE`는 주제 판별의 일시 오류다. 기존 오류 UI에서 message를 표시하고 로딩을 종료한다. 답변이나 done을 기다리지 않는다.
- 판별 중 첫 delta가 늦어질 수 있다. connected/keepalive를 수신해도 로딩은 계속 유지한다. 중지 시 기존 연결 취소를 사용한다.
- 고정 안내·오류·취소도 채팅 요청 한도 1회에 포함된다. 자동 재시도 대신 사용자가 다시 요청하도록 한다.
- `done.usage`는 계속 답변 단계 값이며 고정 안내는 `{}`다. 분류+답변 합계는 서버의 별도 관측 값이므로 프론트에서 이를 전체 비용으로 표시하지 않는다.
- 코드/실행 자료가 없으면 요청할 수 있다. 화면이나 전체 실행 맥락이 자동으로 전송된다고 안내하지 않는다.
- [정책·고정 응답·운영 및 검증 상세](domain-policy.md). 운영 배포 승인은 별도이며 이번 변경에서는 배포하지 않았다.
