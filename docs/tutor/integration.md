# FastAPI 규칙 기반 튜터 이전

## 구현 범위

- `POST /api/v1/tutor/explain`: 컴파일 전 C 줄과 ASM/CRT 해설. `items` 순서대로 응답한다.
- `POST /api/v1/build/compile`: 기존 응답을 유지하고 RV32IM 성공 시 `tutor`를 추가한다. native/실패 시 null.
- `POST /api/v1/simulation/run`: 기존 CORE `result`를 유지하고 바깥에 `tutor`를 추가한다. CORE 계약은 변경하지 않는다.
- 프런트는 컴파일·실행 응답의 해설을 캐시하고 C 줄 선택 시 누락 항목만 요청한다. 재생 중에는 사이클별 해설을 응답에서 조회한다.
- 전체 실행 저장·자동 맥락 조회·AI 실행 분석은 보류. `ContextProvider`는 추후 구현자가 소유권 검사 후 연결하는 인터페이스다.

## 해설 API

```json
{"items":[{"kind":"c","text":"int x = 2;","line":3},{"kind":"asm","text":"lw a0, 0(a1)"},{"kind":"crt","text":"auipc ra, 0","pc":"0x10000"}]}
```

`kind`: c/asm/crt. 항목당 4,096자, 요청당 1~128개, 줄 번호 1 이상. 무료 정적 규칙 처리로 DB 및 외부 모델을 호출하지 않는다. 외부로 공개할 때 기존 게이트웨이 요청 제한 정책을 적용한다.

응답은 `schema_version: "1.0"`, `items`이며 항목은 `kind/category/title/summary/detail/opcode/operands`를 제공한다. CSS 색상은 프런트에서 지정한다. 단일 줄 패턴 분석이므로 C 전체 문법·스코프·실제 최적화 결과를 판정하지 않는다.

## 빌드 응답

`tutor`는 `schema_version`, `source_sha256`(실제 컴파일 소스), `c_lines`, `asm_instructions`를 포함한다. 각 항목은 원본 `text`, 1부터 시작하는 `line`, `explanation`을 갖는다. 빌드 단계에서는 아직 PC가 없어 ASM 원본 줄로 연결한다. C 컴파일 경로가 ASM 텍스트를 생성하지 않으면 `asm_instructions`는 비어 있으며, 시뮬레이션의 코드 매핑에서 명령어 해설을 제공한다. 실제 PC 및 런타임 매핑은 시뮬레이션 결과에서 보완한다. 해설 규칙에 사용하는 텍스트는 줄당 4,096자로 제한한다.

## 시뮬레이션 응답

`tutor.asm_instructions`는 PC, 원본 명령어, source_line, 일반 명령어 해설, 선택적 runtime_explanation을 제공한다. 소스 줄이 없는 매핑은 기존 프런트의 런타임 구분을 따르지만 실제 main 호출 여부는 단정하지 않는다.

`tutor.cycle_explanations`는 이벤트가 있는 사이클만 포함한다.

- `history_index`: 원본 history의 0부터 시작하는 인덱스
- `cycle`: CORE clock 값. 인덱스와 동일하다고 가정하지 않는다.
- `events`: 스톨/포워딩/플러시를 우선순위로 하나만 고르지 않고 모두 반환
- 이벤트마다 `type/title/summary/detail/evidence` 제공
- `evidence`는 해당 CORE 이벤트다. 원인이 없으면 부족함을 명시하고 특정 레지스터·스톨 횟수를 추측하지 않는다.
- `control_hazard_branch_taken`은 분기 또는 점프에 따른 제어 흐름 변경으로 설명한다. 분기 예측 실패라고 단정하지 않는다.


## 반영 순서 및 범위

백엔드를 먼저 배포한 다음 FE의 튜터 응답 연동을 반영한다. 기존 컴파일 및 CORE 결과 필드는 유지하고 `tutor` 필드만 추가한다. DB 마이그레이션, AWS 인프라 변경, 외부 AI 모델 및 API 키는 필요하지 않다.

이 변경은 기존 규칙 기반 해설 이전만 포함한다. AI 채팅 및 전체 실행 맥락을 조회하는 읽기 전용 튜터는 포함하지 않는다. 기존 결과에 `tutor`가 없는 경우 프런트는 명령어 해설을 별도 API로 요청할 수 있지만, 사이클 이벤트 해설은 새 시뮬레이션 응답이 필요하다.
