# CORE 독립 배포와 BE 연동

2026-10-26, Blank Canvas `242925688392` / `ap-northeast-2`.

## 저장소와 배포 단위

- BE: `DKU-ArchReactor/BE`, 현재 작업 폴더. 기존 `archreactor-core` Beanstalk을 유지한다.
- CORE: `DKU-ArchReactor/CORE`, 별도 작업 복제본 `dist/CORE` (BE Git에서는 제외됨).
  기본 브랜치 `main`, 기준 SHA `1bf2957eb2d647a6b8c3983c3fa945a5580dbb83`.
- CORE 기존 `Dockerfile`은 테스트용. 서버용 `Dockerfile.server`를 추가했다.
- 시뮬레이터 계산은 기존 create_state/run_simulation/delete_state를 사용한다.
  계산 파일 변경은 사이클 제한 오류 메시지가 실제 제한 값을 표시하도록 하는 수정뿐이다.
- BE 연동 코드는 GitHub OIDC 배포 설정과 함께 `core`에 반영한다. 별도 `dist/CORE` 복제본의 커밋·푸시는 이 BE 배포 범위에 포함하지 않는다.

## 인프라

| 대상 | 값 |
| --- | --- |
| CORE ECR | `242925688392.dkr.ecr.ap-northeast-2.amazonaws.com/capstone/archreactor-core` |
| CORE 빌드 스택 | `archreactor-simulator-build` |
| CORE 서비스 스택 | `archreactor-simulator-service` |
| CORE CodeBuild | `archreactor-core-image-build` |
| ECS 클러스터/서비스 | `archreactor-simulator` |
| CORE 로그 | `/ecs/archreactor-simulator`, 14일 |
| VPC | `vpc-0965355d4fc1288e2` |
| subnet | `subnet-0c75ad129f7d487e8` |
| 허용 클라이언트 SG | `sg-08805e3f35761f741` (BE) |
| BE 연결 주소 | `simulator.archreactor.internal:50051` |
| BE timeout | `CORE_GRPC_TIMEOUT_SECONDS=12` |

CORE 템플릿은 `dist/CORE/infrastructure/{build,service}.yml`에 있다.
BE는 `infrastructure/environment.yml`의 `CoreGrpcTarget` 매개변수로 연결한다.
CORE 이미지 업데이트는 CORE 서비스 스택의 Image 매개변수만 바꾼다.
BE CloudFormation, Beanstalk, ECR 이미지는 갱신하지 않는다.

Fargate 0.5 vCPU/1 GiB/태스크 1개. 배포 중 최대 2개. 비root·read-only root filesystem.
Cloud Map private DNS가 private task IP를 제공하며 TCP 50051 인바운드는 BE SG만 허용한다.
BE nginx/CloudFront/ALB는 gRPC 경로에 들어가지 않는다. HTTP/2 h2c로 VPC 내부에서 직접 통신한다.
외부에서 CORE를 호출할 수 없다. TLS/mTLS는 초기 구성에 포함하지 않았다.

기존 private subnet에 NAT가 없어 public subnet의 공인 IPv4를 외부 HTTPS 통신에만 사용한다.
별도 NAT/로드밸런서 고정 비용을 추가하지 않는다. 추가 비용: Fargate CPU·메모리,
공인 IPv4, Cloud Map/Route53 private DNS, ECR 저장·스캔, CodeBuild, CloudWatch 로그.
단일 AZ·태스크이므로 고가용성은 보장하지 않으며 DNS TTL 10초 동안 재연결 실패 가능성이 있다.

ECR immutable 태그/스캔/암호화를 적용했다. tagged 릴리스는 자동 삭제하지 않고,
untagged 이미지만 14일 후 만료한다. CORE 빌더 역할은 CORE 저장소와 소스 prefix에만 접근한다.
런타임은 CORE pull 및 로그 execution role만 있고 애플리케이션 AWS task role은 없다.

## API와 호환성

`POST /api/v1/simulation/run`:

```json
{"build_id":"소유한 성공 빌드 UUID","mode":"pipeline","max_cycles":2000}
```

기존 JWT 인증을 사용하며 `build.file.project.user_id` 소유권을 검사한다.
사용자가 임의의 S3 키/URL/다른 사용자의 빌드를 실행할 수 없다.
BE는 제한 크기 내에서 S3 ELF를 읽고 gRPC로 전송한다.

응답은 request_id, execution_id, execution_status, core_version,
result_schema_version, result를 반환한다. result는 기존 CORE JSON의
summary/history/console_output/program/simulator를 포함한다.
정상 종료와 CYCLE_LIMIT/SIMULATION_ERROR를 분리한다.
잘못된 ELF 422, 동시성·결과 한도 429, 연결 실패 503, timeout 504로 매핑한다.

BE에는 `app/contracts/`의 고정 생성 코드만 포함한다. CORE 구현을 패키지로 가져오지 않는다.
계약 `archreactor.v1` 및 JSON 스키마 1.x의 기존 의미를 유지하면 CORE만 갱신 가능하다.
CORE CI는 고정 descriptor 대비 필드/RPC/enum 변경과 생성 코드 일치를 검사한다.
JSON 의미는 CORE 테스트와 BE 실제 샘플 호출로 검증한다. 임의 의미 변경을 정적으로 모두 검출하지는 않는다.
파괴적 변경은 v2 RPC를 병행 제공한 뒤 BE를 별도 이전한다.

## 프로그램 실행과 제한

컴파일 API에 `compile_profile`을 추가했다. 기본값 `rv32im`, 기존 호스트 컴파일은 `native`.
RV32IM/ILP32·freestanding·표준 라이브러리 없음, `.text=0x10000`을 사용한다.
C는 `_start → main → ecall 10`으로 종료하고 ASM은 `_start`를 직접 정의한다.
출력은 교육용 ecall 1(정수), 4(문자열), 종료는 10이다.
컴파일 옵션은 최적화/경고/표준 버전 allowlist로 제한해 ISA·링커 프로파일 변경을 막는다.

CORE 한도: ELF 256 KiB, 로드 메모리 64 KiB, 최대 2,000 cycles, JSON 결과 8 MiB,
요청당 계산 10초, 동시 실행 2개/태스크. 각 실행은 고유 UUID와 별도 프로세스를 사용한다.
오류 시 finally로 상태를 삭제하고, 취소/기한 초과는 프로세스를 종료한다.
250ms 안에 종료하지 않으면 kill하여 메모리를 회수한다. Linux 워커 주소 공간은 384 MiB로 제한한다.
BE HTTP 연결 종료도 gRPC 취소로 전달한다. 단계별 세션·스트리밍은 제공하지 않는다.

## 검증

- CORE CodeBuild: 52개 테스트 통과. 계약 생성 코드·v1 호환성 검사 통과.
- BE CodeBuild: PostgreSQL migration 및 RISC-V 컴파일 포함 26개 테스트 통과.
- 비root·read-only 컨테이너 기동, gRPC health, CORE 샘플 ELF의 ALL PASS 확인.
- 실제 BE 컨테이너에서 샘플 pipeline 135 cycles, timeout 504, 연결 실패 503, 이후 복구 확인.
- 공개 HTTPS API에서 인증·다른 사용자 소유권 차단, RV32IM C 컴파일과 single/pipeline 출력 42,
  cycle limit, concurrent execution_id·상태 분리, native ELF 422 확인.
- 로컬 테스트에서 취소/기한 초과 후 자식 프로세스 종료와 동시성 슬롯 반환 확인.
- cfn-lint, 기존 cfn-guard 규칙, CloudFormation change set 검토 후 적용했다.

상세 실행 결과는 로컬 `dist/core-api-before-update.json`, `dist/core-api-after-update.json` 및
`dist/core-deployment-state.json`에 저장한다. 비밀번호·토큰·DB URL은 저장하지 않는다.
첫 이미지의 ZIP 파일 권한 문제는 수정하고 빌드에 실제 컨테이너 기동 검사를 추가했다.
실패한 초기 서비스 스택은 리소스가 모두 rollback 삭제된 것을 확인한 뒤 빈 스택만 정리했다.

## CORE 팀원의 배포·롤백

CORE 작업 디렉터리에서:

```sh
pip install -r requirements.txt -r requirements-server.txt -r requirements-contract.txt -r requirements-deploy.txt
python scripts/check-contract.py
pytest -q
python scripts/deploy.py
```

배포 스크립트는 로컬 AWS 프로파일 `archreactor-new`를 명시하며 STS 계정을 확인한다.
CodeBuild 테스트→이미지 빌드→ECR push→digest 고정 CloudFormation 배포→ECS/gRPC health 검증 순서다.
태그는 Git SHA와 소스 ZIP SHA256을 포함해 미커밋 변경도 구분한다.
GitHub 워크플로는 CORE 테스트/계약/컨테이너 빌드용이다. CORE GitHub OIDC 배포 연결은 하지 않았다.
현재 실제 배포 경로는 명시적 프로파일과 CodeBuild를 사용하는 위 스크립트다.

롤백은 이전 정상 digest로 실행한다. BE를 배포할 필요가 없다.

```sh
python scripts/deploy.py --rollback sha256:09b73ca3d00fe62644bf735d33399e4d3fe9a0901df22b186c562a3bb6ff7f95
```

더 자세한 계약·한도·운영 방법은 CORE의 `docs/grpc-deployment.md`를 참고한다.

## 실제 배포 이미지와 CORE 단독 업데이트 기록

- 최종 CORE 태그: `core-1bf2957eb2d6-78e5cc5d5c7d7772`
- 최종 CORE digest: `sha256:a7bc12f8a6c9c21cb815c37eaa8901302703b052cbf323298ff539200a4aaf87`
- 이전 정상 CORE 태그: `core-1bf2957eb2d6-22b293dc9816c34c`
- 이전 정상 CORE digest: `sha256:09b73ca3d00fe62644bf735d33399e4d3fe9a0901df22b186c562a3bb6ff7f95`
- ECS 최종 task definition: `archreactor-simulator:3`
- BE 태그: `be-grpc-b75a581b40849933`
- BE digest: `sha256:2c3a5d868abdaf522e72ccd317784150271fb9a4959e4fc9e2fc10955c07ca0a`
- BE version label: `archreactor-environment-version-yyrdkkxwuup5`

CORE 단독 업데이트 전후 BE 컨테이너 ID는
`cef9d5b26a6326603a456fed850fd85d14afc086b68cd7ae632a5f0c70aa170d`로 같았다.
샘플 ELF는 양쪽에서 135 cycles/ALL PASS, timeout·연결 실패·복구도 통과했다.
공개 API의 인증/소유권, 컴파일, single/pipeline 출력 42, cycle limit, 동시 상태 분리,
native ELF 거부 검증도 동일하게 통과했고 응답의 core_version만 바뀌었다.

테스트 파일·빌드 DB 레코드는 API로 삭제하고 이 작업에서 만든 테스트 사용자 4명과 기본 프로젝트도 삭제 완료했다.
S3의 작은 컴파일 테스트 결과물은 기존 파일 삭제 정책에 따라 남아 있으며 임의로 다른 객체를 삭제하지 않았다.
롤백 명령과 이전 정상 digest는 준비했지만, 최종 정상 업데이트를 다시 되돌리는 실운영 롤백은 수행하지 않았다.

최종 확인: CORE CloudFormation `UPDATE_COMPLETE`, ECS `COMPLETED / HEALTHY`, BE `Ready / Green`.
