# 프론트 인수인계: 선택 실행 상태와 튜터 근거

이번 작업에서는 프론트 파일 수정·배포를 하지 않았다. 아래 계약은 맥락 연결 백엔드 PR 배포 후 사용한다. 기존 `messages`만 보내는 채팅은 계속 호환된다. 전체 실행을 AI가 자동으로 읽는다고 표시하지 않는다.

## 1. 실행 결과 준비

로그인 상태에서 기존 `POST /api/v1/simulation/run` 바디에 선택 필드를 추가한다.

```json
{
  "build_id": "<기존 빌드 UUID>",
  "mode": "pipeline",
  "max_cycles": 2000,
  "capture_assistant_context": true
}
```

직접 컴파일 흐름은 `build_id` 대신 기존 `simulation_token`을 사용한다. 둘을 동시에 보내지 않는다. capture=true는 로그인 필수다. 기본 false는 기존 동작과 같다.

응답 바깥 `assistant_context`가 다음과 같으면 **이 실행 응답과 묶어서** 보관한다. `result`만 추출해서 descriptor를 버리지 않는다.

```json
{
  "available": true,
  "execution_id": "<실행 UUID>",
  "result_version": "<64자리 SHA-256>",
  "artifact_sha256": "<64자리 ELF SHA-256>",
  "mode": "pipeline",
  "cycle_min": 0,
  "cycle_max": 133,
  "expires_at": "2026-11-12T12:30:00+00:00"
}
```

저장할 수 없을 때는 `{"available":false,"code":"CONTEXT_UNSUPPORTED_RESULT"}` 또는 `CONTEXT_STORAGE_UNAVAILABLE`다. 시뮬레이션 자체는 성공할 수 있다. 이 경우 맥락 첨부를 비활성화하고 일반 질문은 허용한다. descriptor가 없는 구버전 서버도 같은 방식으로 처리한다.

## 2. 질문 시점의 상태 고정

질문 전송 버튼을 누른 순간 선택한 실행과 clock을 고정한다. 재생이 계속되더라도 이미 보낸 질문의 참조를 바꾸지 않는다. 매 사이클 모델을 호출하지 않는다. `cycle`은 화면의 표시 번호가 아니라 CORE의 0부터 시작하는 `clock`이다.

`POST /api/v1/assistant/chat`, 기존 Bearer 인증/POST fetch/SSE 사용:

```json
{
  "messages": [{"role":"user","content":"이 사이클에서 왜 스톨이 발생했어?"}],
  "context": {
    "execution_id": "<descriptor.execution_id>",
    "result_version": "<descriptor.result_version>",
    "artifact_sha256": "<descriptor.artifact_sha256>",
    "mode": "pipeline",
    "cycle": 17,
    "memory_addresses": [4096, 4100]
  }
}
```

- 실제로 존재하는 주소만 사용자 선택에 따라 넣는다. 위 주소는 문법 예시이며 해당 실행에 있다고 가정하면 안 된다.
- `memory_addresses`는 10진 정수 배열, 4바이트 정렬, 중복 없이 최대 16개다. 생략/빈 배열이면 메모리 값은 보내지 않는다.
- 레지스터·CPI·튜터 해설의 원문을 프론트에서 다시 구성해 보내지 않는다. 서버가 소유한 결과에서 가져온다.
- 일반 질문은 context 생략 또는 null. 오래된 참조 오류가 나면 context를 몰래 빼고 재시도하지 말고 사용자에게 재실행/참조 해제를 알린다.
- 코드 편집·재컴파일·모드 변경·새 실행 선택 시 기존 참조를 무효화한다. 늦게 도착한 이전 실행 응답으로 최신 참조를 덮어쓰지 않도록 요청 세대/실행 ID를 확인한다.

## 3. 답변과 오류 표시

기존 delta/done/error 구조는 유지한다. **허용된 질문에 실제 맥락이 첨부된 경우에만** done에 context가 추가된다.

```text
data: {"type":"delta","text":"..."}

data: {"type":"done","stop_reason":"end_turn","usage":{},"context":{"execution_id":"<UUID>","result_version":"<SHA-256>","artifact_sha256":"<SHA-256>","mode":"pipeline","cycle":17}}
```

답변 카드에 “실행 <ID> · cycle 17 기준(0부터 시작)”을 표시한다. 생성 중에는 전송 시 고정한 참조를 표시할 수 있지만, 완료 후에는 done의 참조를 사용한다. 주제 외/인사/확인 요청의 고정 안내에는 context가 없으며 실행을 분석했다고 표시하지 않는다. 요청한 메모리 주소 목록은 done에 없으므로 프론트의 해당 질문 상태에 보관한다.

SSE 시작 전 HTTP 오류의 `detail.code`:

| HTTP | 코드 | 처리 |
|---|---|---|
| 404 | CONTEXT_NOT_FOUND | 다른 소유자·없는 실행·보관 개수 초과로 제거된 실행. 재선택/재실행 |
| 410 | CONTEXT_EXPIRED | 만료. 재실행 |
| 409 | CONTEXT_MISMATCH | 버전·ELF·모드 불일치 또는 저장 데이터 변동. 참조 해제 후 재실행 |
| 422 | CONTEXT_CYCLE_UNAVAILABLE | 유효한 clock 다시 선택 |
| 422 | CONTEXT_MEMORY_UNAVAILABLE | 실행에 없는 주소 선택 해제 |
| 413 | CONTEXT_TOO_LARGE | 선택 메모리 축소, 계속 실패하면 첨부 해제 안내 |

요청 스키마 오류는 기존 FastAPI 422 검증 배열이다. 로그인 401/403, 한도 429, 비활성 503 및 스트림 이후 error 처리는 기존과 같다. 연결 중단/재시도는 새 질문 요청으로 취급하며 유효한 재요청은 한도가 다시 차감된다.

## 4. 프론트 재개 시 확인할 항목

1. 로그인 시 capture=true → descriptor 저장 → 선택 clock으로 질문 → 완료 참조 표시.
2. single/pipeline, 최초 clock 0, CYCLE_LIMIT/SIMULATION_ERROR도 올바르게 표시.
3. 재생 중 질문, 실행을 빠르게 바꾸기, 코드 편집, 느린 이전 응답이 섞이는 경우 참조 보존/무효화.
4. 메모리 미선택/16개/잘못된 주소, 만료, 3개보다 많이 실행해서 이전 결과가 삭제되는 경우.
5. 다른 계정 전환 시 이전 참조 제거. 외부 사용자 실행 ID는 서버가 404로 차단.
6. 기존 한글 스트리밍·AbortController 중지·오류·재시도·429·분할 UTF-8·done 전 연결 종료.
7. 범위 밖 고정 안내에 실행 근거 배지가 붙지 않음.

C 소스 및 컴파일 C 줄 해설의 자동 전달은 이번 계약에 없다. 일반 질문에 사용자가 텍스트로 붙여넣는 경우에는 기존 메시지로 전달된다.
