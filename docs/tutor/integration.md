# 독립 TUTOR gRPC 해설 연결

BE는 인증·빌드 소유권·컴파일·CORE 호출을 유지하고 해설만 독립 TUTOR 서버에서 받습니다.
기존 Sample RPC와 REST 샘플 경로는 유지합니다. TUTOR 구현 패키지를 BE에 설치하지 않습니다.

## 호출과 설정

- `POST /api/v1/tutor/explain` → Explain RPC. 요청당 최대 128개, 순서와 추가 해설 필드 보존.
- RV32IM 컴파일 성공 → Compile RPC. 기존 응답 외부 `tutor`에 해설 추가.
- 시뮬레이션 결과 → Analyze RPC. 검증된 ELF와 CORE 내부 result를 전달.
- AI 실행 문맥 → Analyze RPC. 별도로 정제한 단계·이벤트만 전달하고 PC 표기를 통일해 저장.

기존 `TUTOR_GRPC_TARGET`과 `TUTOR_GRPC_TIMEOUT_SECONDS`를 사용합니다. 새 HTTP 포트나 환경변수는 필요하지 않습니다.
동기 gRPC는 기존 동기 라우터의 worker 또는 async 시뮬레이션 라우터의 threadpool에서 호출합니다.
TUTOR 수신 제한 16 MiB, 응답 제한 32 MiB를 BE에도 적용합니다.

## 실패 격리

TUTOR 미설정·장애·구버전은 컴파일/시뮬레이션의 `tutor: null`로 처리합니다. 내부 CORE result는 변경하지 않습니다.
명시적 해설 요청은 잘못된 입력 422, 메시지/자원 제한 413/429, 사용 불가 503, 시간 초과 504,
요청 ID·schema·응답 형식 불일치 502를 반환합니다. 입력·내부 RPC 오류 상세는 노출하지 않습니다.

AI 실행 문맥은 해설 장애 시에도 프레임을 보존하고 `tutor.available=false`로 저장합니다.
부분 이력에서 산출된 완료 횟수, 파일 경로·전체 소스 메타데이터는 AI 문맥에 포함하지 않습니다.
문법 기반 의미와 실제 관찰된 레지스터·메모리 값을 구별합니다.

## 검증

```powershell
$env:DEBUG='false'
$env:CORE_SOURCE='C:\Users\User\ArchReactor\CORE'
python -X utf8 -m pytest -q
python -X utf8 scripts/verify-tutor-local.py --tutor-source ..\TUTOR-grpc
```

일반 BE 테스트는 독립 계약 fixture를 사용합니다. 마지막 명령은 실제 TUTOR 서버를 임시 기동하고
배포된 BE에서 컴파일·실행한 결과를 BE 클라이언트로 분석합니다. DB·AWS 변경·외부 LLM 호출은 하지 않습니다.

새 TUTOR를 먼저 리뷰·배포한 후 BE, FE 순서로 적용합니다.
현재는 로컬 `feat/tutor-grpc-analysis` 브랜치이며 운영 배포와 PR은 생성하지 않았습니다.
