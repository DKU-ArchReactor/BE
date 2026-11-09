# 프론트 인수인계: 규칙 기반 튜터와 AI 어시스턴트

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

`GET /api/v1/assistant/status` 응답:

```json
{"enabled":false,"code":"AGENT_NOT_CONFIGURED"}
```

false일 때 입력/전송을 비활성화하고 ‘AI 어시스턴트 연결 준비 중’ 안내를 보여준다. 이 값은 설정 플래그이며, true만으로 실제 Bedrock 모델 접근 성공을 보장하지는 않는다. API 키 입력 UI는 만들지 않는다.

## 3. 채팅 계약 (활성화 후)

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
