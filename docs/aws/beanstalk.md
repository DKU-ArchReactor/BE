# core 브랜치의 Elastic Beanstalk 배포

대상은 **Blank Canvas 배포 계정 `242925688392` / 서울 `ap-northeast-2`**이다.
현재 작업 폴더는 `core` 브랜치이다. 최초 배포는 검토한 로컬 소스를 CodeBuild에서 테스트·빌드하고 ECR 이미지로 배포한다. GitHub Actions 자동 배포는 별도 OIDC 역할·저장소 변수 설정과 커밋·푸시 후 사용할 수 있다.

## 배포 결과 (2026-10-26)

- HTTPS API: https://d1j3nkcez6kncs.cloudfront.net/
- HTTPS Swagger: https://d1j3nkcez6kncs.cloudfront.net/docs
- 기존 HTTP 원본: http://archreactor-core-242925688392.ap-northeast-2.elasticbeanstalk.com/
- 환경: `archreactor-core` (`e-nygnvhdugs`), `Ready / Green / Ok` 확인. 네 CloudFormation 스택의 생성·업데이트 완료를 확인했다.
- 이미지: `242925688392.dkr.ecr.ap-northeast-2.amazonaws.com/capstone/archreactor:core-14f1dbc95f81556e`
- 이미지 digest: `sha256:bc8598bca6e77868beea9959d8ea2adab2c94a00a3ee062227c2642a4964d47e`
- 초기 앱 버전: `archreactor-environment-version-loakzvqhlxdc`.
- CodeBuild에서 PostgreSQL 마이그레이션 검증을 포함한 테스트 **15개 통과**.
- 실제 API에서 상태 확인, Swagger, 인증 없는 접근 차단, 회원가입·로그인, 파일 저장·조회·삭제, 컴파일, S3 어셈블리·ELF 다운로드를 검증했다.
- RDS PostgreSQL `16.15`가 `available`이며, 비공개·암호화·7일 백업·삭제 방지를 확인했다.
- EC2 `t3.small` 1대, IMDSv2 필수 및 응답 hop limit 2를 확인했다.

테스트용 사용자 `deploy_smoke_302e4ee33e9b`와 기본 프로젝트는 DB에 남아 있다. 임시 비밀번호·토큰은 저장하지 않았으며 테스트 소스와 연관 빌드 DB 레코드는 삭제했다. 다운로드 확인에 사용한 작은 S3 결과물은 남아 있다. 검증 기록과 배포 상태는 Git에서 제외한 로컬 `dist/smoke-result.json`, `dist/deploy-state.json`에 보관한다.

CloudFront와 원본 서버 사이에도 공인 인증서를 적용해 **브라우저→CloudFront→서버까지 HTTPS**로 연결한다. API/S3 CORS는 현재 `http://localhost:5173`만 등록했다. GitHub OIDC 역할·저장소 변수는 아직 연결하지 않았으며, 자동 배포를 사용하려면 아래 설정이 필요하다.

## 도메인 구매 없이 전체 외부 구간 HTTPS

- [HTTPS API](https://d1j3nkcez6kncs.cloudfront.net/), [Swagger](https://d1j3nkcez6kncs.cloudfront.net/docs)
- [CloudFront 설정 콘솔](https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E2M6BJLU88POAS)
- 브라우저 → CloudFront → Beanstalk nginx까지 HTTPS이다. nginx → 같은 EC2의 앱 컨테이너는 로컬 HTTP 프록시이고, RDS 연결은 기존 `sslmode=require`를 유지한다.

추가 도메인을 구매하지 않고 **기존 Beanstalk 기본 호스트명**에 Let's Encrypt 공인 인증서를 발급했다. CloudFront는 기본 `cloudfront.net` 인증서를 사용하며 원본 연결은 `https-only`, TLS 1.2, 포트 443으로 구성한다. 자체 서명 인증서나 인증서 검증 우회는 사용하지 않는다. 인증서 문제 시 HTTP로 자동 후퇴하지 않는다.

원본 인증서의 호스트명은 `archreactor-core-242925688392.ap-northeast-2.elasticbeanstalk.com`이다. 2026-10-26 최초 발급 인증서 만료일은 **2027-01-24**이며, 서버 내부에서 신뢰 체인·호스트명을 검증한 HTTPS 요청과 Certbot 갱신 모의 테스트가 통과했다.

2026-10-26 최종 설정에서 Beanstalk `Ready/Green`, CloudFront `Deployed` 및 원본 `https-only`를 확인했다. HTTP API 전환을 켠 상태에서도 갱신 모의 테스트와 nginx 재적용이 성공했다. 공개 HTTPS 주소에서 회원가입·로그인·파일 저장·컴파일·S3 다운로드가 통과했으며, 기록은 로컬 `dist/smoke-result-origin-tls.json`에 보관한다.

### 발급·갱신과 서버 재배포

- [setup-origin-tls.sh](../../scripts/setup-origin-tls.sh)는 Beanstalk 호스트에서 Certbot 5.4.0을 별도 Python 환경에 설치하고 HTTP-01로 인증한다. 최초 발급 전 staging 검증을 거친다.
- `.platform/hooks/postdeploy`와 `.platform/confighooks/postdeploy`에서 실행해 앱 배포 및 환경 설정 변경 후 HTTPS 프록시 설정을 재적용한다. 비밀값이 없는 해당 훅과 설치 스크립트만 `Dockerrun.aws.json`과 함께 ZIP에 담는다.
- 개인키와 ACME 계정 정보는 서버의 root 전용 `/etc/letsencrypt`에만 보관한다. Git, 배포 ZIP, 로컬 출력, 앱 환경변수에 넣지 않는다.
- `archreactor-origin-tls-renew.timer`가 하루 두 번 무작위 지연을 두고 갱신 필요 여부를 확인한다. 갱신 성공 후 nginx 설정을 검사하고 인증서를 다시 로드한다.
- 인스턴스 교체 시 새 서버에서 다시 발급한다. 같은 호스트명의 잦은 교체·재발급은 인증기관의 발급 제한에 걸릴 수 있으므로 불필요한 환경 재생성을 피한다. 로컬 파일 보존 방식이므로 인증서 갱신 로그와 타이머 상태를 점검한다.
- Systems Manager로 SSH 포트 개방 없이 서버를 점검할 수 있도록 인스턴스 역할에 `AmazonSSMManagedInstanceCore`를 연결했다. 비밀값을 출력하는 명령은 실행하지 않는다.

### 원본 접근과 전환 순서

원본 포트 443은 서울의 AWS 관리형 CloudFront origin-facing prefix list(`pl-22a6434b`)만 허용한다. 일반 외부 클라이언트는 CloudFront 주소로 접속한다. HTTP 포트 80은 ACME 검증과 최소 상태 확인 `/`에 필요하며, 일반 API 경로는 CloudFront HTTPS 주소로 308 전환한다.

`OriginTlsHost`, `PublicHttpsHost`, `OriginHttpsOnly`는 [environment.yml](../../infrastructure/environment.yml)의 매개변수다. 초기 구성은 다음 순서로 전환한다.

1. `OriginHttpsOnly=false`에서 원본 인증서·HTTPS 서버·갱신 타이머를 준비한다.
2. 인증서 검증 후 [https.yml](../../infrastructure/https.yml)의 CloudFront 원본을 HTTPS 전용으로 전환하고 `Deployed`를 기다린다.
3. `OriginHttpsOnly=true`를 적용해 원본의 일반 HTTP API 경로를 HTTPS로 전환한다.

CloudFront HTTPS 전환 전에 3번을 적용하면 리다이렉트가 반복될 수 있다. 업데이트 중 단일 서버의 짧은 중단은 가능하다. 갱신 실패 시 `journalctl -u archreactor-origin-tls-renew.service`와 인증서 만료일을 확인하고 원인을 수정하며, HTTP로 되돌려 우회하지 않는다.

### CloudFront API 설정

- `Managed-CachingDisabled`: API 캐시 TTL 0. 브라우저에도 `Cache-Control: no-store` 적용.
- `Managed-AllViewerExceptHostHeader`: 인증 헤더·쿠키·쿼리를 전달하고 Host는 원본 호스트명으로 설정. 모든 API HTTP 메서드 허용.
- HTTP→HTTPS 전환과 원본 절대 리다이렉트의 HTTPS 주소 유지. HSTS, nosniff, 프레임 차단, Swagger/ReDoc 호환 CSP 적용.
- 비공개 SSE-S3 로그 버킷 사용. 현재 로그와 이전 버전은 각각 30일 만료, 쿠키 기록 비활성. URL 쿼리는 로그에 남을 수 있으므로 비밀값을 넣지 않는다.
- CloudFront 요청·전송량 및 S3 로그에 사용량 요금이 발생할 수 있다. 별도 도메인 구매·로드밸런서·유료 WAF/Shield Advanced 구독은 추가하지 않았다. CloudTrail은 기존 이벤트 기록 범위이며 장기 trail은 별도 구성하지 않았다.
- 서버와 DB는 서울에 유지한다. CloudFront는 전역 서비스다. 프론트 주소의 API/S3 CORS 등록은 별도로 필요하며, 같은 출처의 Swagger에는 추가 CORS 등록이 필요 없다.

### 배포 사전 점검: 서울 리전 접근 제한

2026-10-26 확인 결과, 서울의 `ec2:DescribeVpcs`와 `ecr:DescribeRepositories`가 조직 SCP `p-c5q03m5w`의 명시적 Deny로 거부됐다. 같은 프로파일의 시드니 ECR 조회는 성공했다. 2026-10-26 사용자 승인 후 아래 계정 한정 예외를 적용해 해소했다.

정책 소유 관리 계정은 `731732399204`이며, Blank Canvas 역할에는 해당 정책의 `organizations:DescribePolicy` 권한이 없다. 별도 `archreactor-management` 프로파일로 관리 계정 인증 후 조회했다. 정책 이름은 `AdvancedModeRegionRestrictionSecurityControlPolicy`이며 조직 루트 `r-0s5h`에 연결되어 있다. `RegionFloor`가 서울을 제외한 리전 목록으로 접근을 제한한다.

Blank Canvas에만 서울을 허용하는 변경안과 원본 백업은 로컬 `dist/aws-policy-backup-20261026/`에 보관했다. 기존 `RegionFloor`를 다른 계정에 유지하고, 대상 계정용 `RegionFloorBlankCanvas`에만 서울을 추가하는 방식이다. AWS IAM 시뮬레이터에서 대상 계정의 서울 요청만 허용하고 다른 계정의 서울 및 대상 계정의 도쿄 요청은 명시적 거부로 유지됨을 확인했다. **사용자 승인 후 정책 적용을 완료했다.** 원본·적용 응답·시뮬레이션 결과를 함께 보관했다. 정책을 삭제하거나 분리하지 않았다.

정책 변경 후 `archreactor-new` 프로파일로 서울 VPC/ECR 조회가 성공했고 리소스 생성을 진행했다. 배포 대상 계정은 계속 `242925688392`이며 관리 계정에 배포하지 않는다.

| 항목 | 사용할 값 |
| --- | --- |
| AWS 계정 | `242925688392` |
| 리전 | `ap-northeast-2` |
| Beanstalk 애플리케이션 | `archreactor` |
| Beanstalk 환경 | `archreactor-core` |
| ECR private 저장소 | `capstone/archreactor` |
| 앱 결과물 S3 버킷 | `archreactor-artifacts-242925688392-ap-northeast-2` |
| 배포 ZIP S3 버킷 | `elasticbeanstalk-ap-northeast-2-242925688392` |
| EC2 인스턴스 역할 | `archreactor-eb-ec2-role` |
| GitHub 배포 역할 | `archreactor-github-deploy` |
| RDS 초기 DB 이름 | `archreactor` |

리소스 이름을 다르게 정하면 IAM JSON, GitHub 변수, 앱 환경변수도 같이 바꾼다.
이전 계정의 EC2, S3, DB는 이 설정으로 변경되거나 삭제되지 않는다.
기존 데이터가 필요하면 이전 DB의 백업/복원과 S3 복사를 별도로 진행해야 한다. 새 AWS 계정 ID만 입력해서 데이터가 이동되지는 않는다.

## 현재 CloudFormation 구성과 재배포

콘솔 수동 생성 대신 다음 템플릿으로 관리한다. 아래의 콘솔 안내는 구성을 이해하거나 다른 환경을 만들 때 참고하며, 같은 이름의 리소스를 중복 생성하지 않는다.

| 스택 | 템플릿 | 구성 |
| --- | --- | --- |
| `archreactor-build` | [build.yml](../../infrastructure/build.yml) | ECR, 배포 S3, CodeBuild, 빌드 로그·역할 |
| `archreactor-runtime` | [runtime.yml](../../infrastructure/runtime.yml) | VPC, private RDS, 결과물 S3, Secrets Manager, KMS, 런타임 역할 |
| `archreactor-environment` | [environment.yml](../../infrastructure/environment.yml) | Beanstalk 앱·초기 버전·환경 |
| `archreactor-https` | [https.yml](../../infrastructure/https.yml) | CloudFront HTTPS, 응답 헤더, 접근 로그 |

사용자가 선택한 시연용 구성은 **t3.small 1대 + PostgreSQL 16 / db.t4g.micro Single-AZ**이다. RDS는 private subnet에 있고 TLS를 강제하며, 앱 보안 그룹에서만 5432 포트 접근을 허용한다. DB 암호화, 7일 백업, 삭제 방지를 설정했다. NAT Gateway와 로드밸런서는 만들지 않으며, 공개 API는 CloudFront HTTPS 주소로 제공하며 원본도 HTTPS로 연결한다. 배포·장애 시 중단될 수 있다.

Beanstalk 서비스용 배포 버킷은 AWS 요구사항에 맞게 `BucketOwnerPreferred`로 ACL을 활성화하며, 퍼블릭 접근 차단 4개 설정과 암호화를 유지한다. 앱 결과물 버킷은 ACL 비활성 기본값을 사용한다. [AWS 공식 설명](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/AWSHowTo.S3.html)

DB 암호와 JWT 키는 AWS에서 생성한다. Beanstalk은 `DATABASE_URL`, `JWT_SECRET_KEY`를 Secrets Manager ARN으로 참조한다. 비밀값은 소스 ZIP, 로컬 출력, 환경 설정의 평문 값으로 전달하지 않는다. 앱은 EC2 역할로 S3에 접근한다.

자동 비밀값 교체는 구성하지 않았다. DB 암호를 교체하려면 DB와 credentials secret, URL secret을 함께 갱신하고 Beanstalk 환경의 비밀값을 다시 로드해야 한다. JWT 키 변경은 기존 로그인 토큰을 무효화한다. KMS 키의 자동 교체와 DB 암호 자동 교체는 서로 다른 설정이다.

초기 환경이 `Ready / Green`이면 로컬 Docker 없이 다음 명령으로 재배포할 수 있다.

```bash
python3 scripts/deploy-aws.py --aws /Users/yunsung/.local/bin/aws
```

이 명령은 계정 ID를 검증하고, 허용 목록의 소스만 ZIP으로 만들며, CodeBuild에서 PostgreSQL을 사용한 테스트와 이미지 빌드를 수행한다. 성공한 이미지를 ECR에 올린 뒤 Beanstalk 버전을 갱신한다. 로컬 `.env`와 Git 데이터는 포함하지 않는다. 로그인 만료 시 `archreactor-new` 프로파일로 재인증한다.

템플릿 변경은 CloudFormation change set을 검토해 적용한다. 후속 앱 배포는 Beanstalk API로 버전을 관리하므로, 환경 스택 업데이트 시 `VersionLabel`이 초기 버전으로 되돌아가지 않도록 현재 버전을 반영해야 한다.

EC2·RDS·스토리지·공인 IPv4·KMS·Secrets Manager·로그·CodeBuild 등에 사용 요금이 발생한다. DB/S3/ECR/일부 키와 비밀값은 `Retain`이므로 스택 삭제만으로 데이터와 비용이 모두 제거되지 않는다. 시연 종료 후 필요한 백업을 남기고 별도로 정리한다. CloudWatch 로그를 사용하며, 별도의 장기 CloudTrail trail은 이번 배포에서 만들지 않았다.

## 1. 새 계정과 리소스 준비

1. AWS 콘솔 오른쪽 위에서 계정 ID가 `242925688392`인지 확인하고 리전을 서울로 설정한다.
2. ECR → Private registry → Repositories에서 `capstone/archreactor`를 생성한다. 이미지 태그는 Git commit/run별로 고유하므로 tag immutability를 켜도 된다.
3. S3에 앱 결과물 버킷 `archreactor-artifacts-242925688392-ap-northeast-2`를 서울 리전으로 생성한다. Block Public Access를 켜고 기본 SSE-S3 암호화를 사용한다. 앱은 presigned URL로 결과물을 읽는다.
4. PostgreSQL은 새 계정에서 준비한다. RDS → 데이터베이스 생성 → PostgreSQL, 초기 DB 이름 `archreactor`, 사용자 이름과 암호를 지정한다. 예제/CI는 PostgreSQL 16을 사용한다. 기존에 새 계정에 만들어 둔 PostgreSQL이 있다면 재사용할 수 있다.
5. DB는 Beanstalk과 같은 VPC에 두고 Public access는 No로 설정한다. DB 보안 그룹의 TCP 5432 인바운드는 아래에서 만드는 **Beanstalk 인스턴스 보안 그룹**을 소스로 허용한다. DB를 인터넷 전체에 개방하지 않는다.
6. VPC에 `archreactor-eb-app` 보안 그룹을 만들어 둔다. 이후 Beanstalk 인스턴스에 이 그룹을 추가하면 DB 인바운드 규칙의 소스를 미리 지정할 수 있다. 인터넷 트래픽용 규칙은 Beanstalk이 생성하는 웹 보안 그룹을 사용한다.

외부 PostgreSQL을 쓴다면 연결 가능한 네트워크와 SSL 설정을 해당 서비스에 맞춘다. 이전 `.env`의 DB 주소가 새 계정의 DB라는 보장은 없다.

## 2. IAM 역할 두 종류 준비

### Beanstalk 인스턴스 역할

IAM → Roles → Create role → AWS service → EC2로 `archreactor-eb-ec2-role`을 만든다.

- AWS 관리형 정책 `AWSElasticBeanstalkWebTier`를 연결한다.
- [instance-app-policy.json](instance-app-policy.json)을 인라인 정책으로 추가한다. 지정한 ECR 이미지 읽기, 배포 ZIP 읽기, 앱 버킷의 `builds/*` 읽기/쓰기를 허용한다.
- 인스턴스 프로파일로 이 역할을 Beanstalk에 선택한다.

별도로 **Beanstalk service role**도 필요하다. 환경 생성 화면에서 기본 service role 생성을 선택한다. 직접 만들면 Beanstalk 신뢰 정책과 `AWSElasticBeanstalkEnhancedHealth`, `AWSElasticBeanstalkManagedUpdatesCustomerRolePolicy`를 구성한다.

Beanstalk에서 `AWS_ACCESS_KEY_ID`와 `AWS_SECRET_ACCESS_KEY`는 등록하지 않는다. boto3와 ECR pull은 인스턴스 역할을 사용한다.

### GitHub 배포 역할

1. IAM → Identity providers → Add provider → OpenID Connect.
2. Provider URL: `https://token.actions.githubusercontent.com`, Audience: `sts.amazonaws.com`.
3. IAM → Roles에서 `archreactor-github-deploy`를 만들고 [github-oidc-trust.json](github-oidc-trust.json)을 Trust policy로 사용한다.
4. [github-deploy-policy.json](github-deploy-policy.json)을 Permissions의 인라인 정책으로 추가한다.

현재 신뢰 정책은 **`DKU-ArchReactor/BE`의 `core` 브랜치**만 허용한다. 개인 포크 `Ycastle1/BE`에서 배포할 경우 `sub`의 저장소 이름을 그 값으로 바꿔야 한다. 두 저장소 중 실제로 배포할 하나에만 GitHub 변수를 설정한다.

이 저장소가 immutable OIDC subject 형식에 옵트인한 경우, GitHub의 실제 `sub` 형식(owner/repo ID 포함)에 맞춰 신뢰 정책을 수정한다. 배포 job에는 GitHub Environment를 사용하지 않으므로 신뢰 정책도 브랜치 형식이다.

배포 역할은 기존 환경에 버전을 배포하기 위한 것이다. 현재 초기 ECR, DB, Beanstalk 환경 등은 위 CloudFormation 템플릿으로 생성한다. 정책은 같은 계정/리전과 SSE-S3 버킷을 전제로 한다. 조직의 SCP, permissions boundary, 별도 KMS 키가 있다면 해당 제한/키 권한을 추가로 확인한다.

## 3. Beanstalk 환경 생성

Elastic Beanstalk → Create application/environment에서 다음을 선택한다.

| 설정 | 값 |
| --- | --- |
| Application | `archreactor` |
| Environment tier | Web server environment |
| Environment name | `archreactor-core` |
| Mode(표시되는 경우) | Standard |
| Platform | Docker |
| Platform branch | Docker running on 64bit Amazon Linux 2023 |
| Initial application code | Sample application |
| Service role | 위에서 만든 Beanstalk service role |
| EC2 instance profile | `archreactor-eb-ec2-role` |
| Architecture | x86_64 (이미지는 `linux/amd64`로 빌드) |
| VPC | DB와 같은 VPC |
| EC2 security groups | `archreactor-eb-app` 추가 |

새 환경을 수동 생성한다면 먼저 샘플 앱으로 준비하고, 현재 관리 중인 환경에는 위 CloudFormation 구성과 TLS 훅을 유지한 배포 ZIP을 사용한다. 소스 전체를 ZIP으로 올리면 기존 개발용 `Dockerfile`/`docker-compose.yml`이 선택될 수 있으므로 사용하지 않는다.

간단한 데모는 Single instance로 시작할 수 있다. 컴파일 기능이 있어 메모리는 2 GiB 이상인 x86 인스턴스를 시작점으로 권장하며 실제 부하를 보고 조정한다. 단일 인스턴스 배포는 업데이트 중 중단이 생길 수 있다. 현재 HTTPS는 위의 CloudFront와 호스트 인증서 구성으로 제공한다. 여러 인스턴스로 가용성을 높이려면 Load balanced 환경 + Application Load Balancer를 고려한다. EC2, RDS, 로드밸런서 등의 실제 사용 요금은 별도다.

공용 웹 환경에서 NAT 없이 시작하려면 인터넷 게이트웨이 경로가 있는 public subnet과 인스턴스 public IP를 사용한다. RDS는 private subnet에 둔다. 인스턴스를 private subnet에 두면 ECR/S3/로그 등에 접근할 NAT 또는 적절한 VPC endpoint가 필요하다.

환경 생성 후 S3에서 `elasticbeanstalk-ap-northeast-2-242925688392` 버킷이 생겼는지 확인한다. 없으면 같은 이름의 private 버킷을 서울에 생성한다. 이 버킷은 배포 ZIP 보관용이며 앱 결과물 버킷과 다르다.

환경 → Configuration에서:

- Health reporting: Enhanced.
- 로드밸런서 사용 시 Default process health check path: `/`, 성공 코드 `200`.
- CloudWatch log streaming 활성화, 필요한 보존 기간 설정.
- Rolling deployment를 쓰면 DB 변경이 이전 버전 앱과도 호환되도록 마이그레이션을 작성한다.

`GET /`는 앱 프로세스 상태만 검사한다. 컨테이너 시작 시 DB 마이그레이션이 성공해야 서버가 시작되지만, 이 경로가 지속적인 DB/S3 상태 확인을 대신하지는 않는다.

## 4. Beanstalk 앱 환경변수

환경 → Configuration → Updates, monitoring, and logging(플랫폼/UI에 따라 Software) → Environment properties에 입력한다.

| 이름 | 입력할 값 |
| --- | --- |
| `APP_NAME` | `ArchReactor` |
| `DEBUG` | `false` |
| `DATABASE_URL` | Secrets Manager `archreactor-core/database-url`의 ARN 참조 |
| `JWT_SECRET_KEY` | Secrets Manager `archreactor-core/jwt-key`의 ARN 참조 |
| `AWS_REGION` | `ap-northeast-2` |
| `AWS_S3_BUCKET` | `archreactor-artifacts-242925688392-ap-northeast-2` |
| `CORS_ORIGINS` | `["https://실제-프론트-주소","http://localhost:5173"]` |
| `S3_PRESIGN_EXPIRES_SECONDS` | `300` |

`CORS_ORIGINS`는 JSON 배열이며 도메인 끝에 `/`를 붙이지 않는다. 운영에서 필요 없는 localhost 항목은 제거한다. 비밀번호의 `@`, `:`, `%`, `/` 등은 URL 인코딩한다. Alembic에도 인코딩된 비밀번호가 전달되도록 처리했다.

현재 템플릿은 JWT 키를 Secrets Manager에서 생성한다. 콘솔에서 설정을 바꿀 때도 비밀값을 출력·복사하기보다 secret ARN 참조를 유지한다. 키를 바꾸면 이전 로그인 토큰은 사용할 수 없다.

민감한 DB URL/JWT 키는 지원되는 플랫폼에서 Secrets Manager 또는 SSM Parameter Store의 환경변수 참조로 넣을 수도 있다. 이 경우 인스턴스 역할에 해당 secret/parameter 읽기 및 사용한 KMS 키의 복호화 권한이 추가로 필요하다.

프론트가 presigned URL을 `fetch`로 읽으면 S3 버킷 Permissions → CORS에도 실제 프론트 주소를 추가한다. API CORS와 S3 CORS는 별개다.

```json
[
  {
    "AllowedOrigins": ["https://실제-프론트-주소", "http://localhost:5173"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"]
  }
]
```

## 5. GitHub 저장소 변수 설정

실제로 배포하는 저장소의 Settings → Secrets and variables → Actions → **Variables**에 등록한다.

| Repository variable | 값 |
| --- | --- |
| `AWS_ROLE_ARN` | `arn:aws:iam::242925688392:role/archreactor-github-deploy` |
| `ECR_REPOSITORY` | `capstone/archreactor` (생략 시 동일한 기본값) |
| `EB_APPLICATION_NAME` | `archreactor` |
| `EB_ENVIRONMENT_NAME` | `archreactor-core` |
| `EB_DEPLOY_BUCKET` | `elasticbeanstalk-ap-northeast-2-242925688392` |
| `PUBLIC_API_URL` | `https://d1j3nkcez6kncs.cloudfront.net` (생략 시 동일한 기본값) |

계정 ID와 리전은 workflow에 명시되어 있다. OIDC 인증 결과가 `242925688392`가 아니면 배포가 실패한다.
기존 Secrets의 `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY`는 새 workflow에서 참조하지 않는다. 다른 workflow에서 사용 중인지 확인한 후 필요 없으면 GitHub에서 제거하고 이전 계정의 불필요한 키도 비활성화한다.

## 6. GitHub Actions 배포와 확인

이 변경을 **설정을 등록한 저장소의 `core` 브랜치에 커밋·푸시**하면 자동으로 실행된다.

1. Python 3.11 테스트와 임시 PostgreSQL 마이그레이션 검증.
2. `Dockerfile.prod`로 x86_64 이미지를 빌드하고 새 계정 ECR에 업로드.
3. `Dockerrun.aws.json` v1과 검토한 호스트 TLS 설치·갱신 훅만 포함한 ZIP 생성. 개발용 Compose나 로컬 `.env`는 포함하지 않는다.
4. 배포 ZIP을 S3에 올리고 Beanstalk 버전 등록 → 환경 업데이트.
5. 컨테이너 시작 시 `python -m app.migrate` 실행 → 성공 시 Gunicorn 시작.
6. 배포 버전, Ready/Green 상태, 공개 HTTPS 주소의 실제 `GET /` 응답 확인.

Actions → Deploy core to Elastic Beanstalk에서 결과를 확인한다. 수동 실행 버튼은 workflow 파일이 저장소 기본 브랜치에도 있어야 표시될 수 있다. 기본 브랜치에 없으면 `core` push 경로를 사용한다. 기본 브랜치에 등록한 뒤 수동 실행할 때도 `core`를 선택해야 배포 job이 실행된다.

배포 후 `/docs`에서 회원가입/로그인 → 파일 저장 → 컴파일 → 결과물 S3 다운로드를 확인한다. 루트 상태 확인만 성공해도 S3 권한이나 모든 API 동작이 검증되는 것은 아니다.

기존 컴파일 API는 일반 `gcc`를 사용한다. RISC-V 크로스 컴파일러와 미구현 API(`/objdump`, `/logs`)는 이번 배포 설정 변경 범위에 포함되지 않는다.

## 7. 로컬 AWS 정보 교체

기존 `.env`에는 이전 AWS 인증 정보와 DB 연결값이 있으므로 계정 전환이 완료되기 전에 그대로 운영 명령을 실행하지 않는다. 이 변경에서는 실제 비밀값을 읽어 출력하거나 `.env`를 덮어쓰지 않았다.

1. 저장소의 `.env.example`을 `.env.new-account`로 복사한다.
2. 새 계정의 DB 주소/사용자/암호, 새 JWT 키, 새 계정의 로컬 개발용 AWS 인증 정보를 입력한다. 예제의 `REPLACE_...` 값은 실제 연결값이 아니다.
3. 새 계정에 만들어진 S3 이름을 확인한다.
4. 기존 `.env`를 `.env.previous-account`처럼 Git에서 제외되는 이름으로 보관한 뒤, 준비한 파일을 `.env`로 교체한다. 백업 파일 역시 비밀정보이므로 공유하지 않는다.
5. 필요한 경우 로컬에서 `python -m app.migrate` 후 `uvicorn app.main:app --reload`로 확인한다. 이 단계는 지정한 새 DB에 스키마를 생성/변경한다.

로컬 IAM 사용자의 키를 생성할 때는 앱 버킷에 필요한 범위만 허용하고, Beanstalk에는 이 키를 복사하지 않는다. 로컬에서 임시 자격증명을 쓸 경우 SDK 프로파일/환경변수 방식으로 설정하고 `.env`의 액세스 키 두 항목은 제거한다.

## 실패 확인 및 롤백

- ECR pull 실패: 새 계정/서울 ECR에 해당 태그가 존재하는지, 인스턴스 역할에 ECR 읽기 권한이 있는지 확인.
- DB 연결 실패: 새 endpoint, DB 이름, URL 인코딩, 동일 VPC, RDS 5432 인바운드 소스 보안 그룹 확인.
- S3 AccessDenied: `AWS_S3_BUCKET`, 인스턴스 역할의 `builds/*` GetObject/PutObject, 버킷 정책 확인.
- 컨테이너에서 IAM 자격증명을 찾지 못함: 인스턴스 역할 부착과 IMDS 접근 확인. IMDSv2의 응답 hop limit이 1이면 컨테이너에서 접근하지 못할 수 있어 2가 필요하다. 환경의 launch template 설정에도 반영해야 인스턴스 교체 후 유지된다.
- 브라우저 CORS 오류: 정확한 프로토콜·도메인·포트가 API 및 S3 CORS에 등록됐는지 확인.
- Beanstalk Events 및 Logs → Full logs에서 `/var/log/eb-engine.log`와 Docker 앱 로그 확인.

DB 연결은 10초, 마이그레이션 lock 대기는 120초로 제한한다. 실패 시 서버를 시작하지 않고 컨테이너가 실패하도록 했다. 여러 컨테이너가 동시에 시작하면 PostgreSQL advisory lock과 같은 트랜잭션/연결로 Alembic을 실행한다.

롤백은 Beanstalk Application versions에서 이전 성공 버전을 선택해 환경에 배포한다. **앱 버전 롤백은 DB 스키마를 되돌리지 않는다.** 파괴적인 마이그레이션 전에는 DB 백업과 호환성 계획이 필요하다. ECR 이미지와 해당 배포 ZIP은 롤백에 필요한 기간 동안 보관한다.

HTTPS 프론트의 API 주소는 `https://d1j3nkcez6kncs.cloudfront.net`으로 설정한다. GitHub workflow와 로컬 배포 스크립트도 이 HTTPS 주소에서 상태를 확인한다. 향후 소유 도메인과 로드밸런서 환경을 도입한다면 서울 ACM 인증서와 ALB HTTPS 리스너, DNS를 별도로 설정한다.

## 공식 참고 문서

- [Beanstalk Docker 배포와 Dockerrun v1](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/single-container-docker-configuration.html)
- [ECR 인증과 인스턴스 역할](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/docker-configuration.remote-repo.html)
- [Beanstalk 인스턴스 프로파일](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/iam-instanceprofile.html)
- [Beanstalk service role](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/concepts-roles-service.html)
- [GitHub OIDC와 AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [Alembic 연결 공유](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands)
