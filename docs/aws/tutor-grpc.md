# TUTOR Fargate and BE REST integration

## Scope

`POST /api/v1/tutor/sample` calls the independent `archreactor.tutor.v1.Tutor/Sample` gRPC service. This remains a public connectivity sample: no model calls, code execution, database access, or saved conversation.

The local analysis branch also connects `/tutor/explain`, compilation and execution explanations to new Explain/Compile/Analyze RPCs on the same service and port. See [the tutor integration contract](../tutor/integration.md). These changes are not deployed yet; the historical sample deployment record below does not prove analysis deployment.

Request: `{"message":"Hello TUTOR"}`. Maximum 256 characters / 1024 UTF-8 bytes, nonblank. Extra fields are rejected.

Response includes `request_id`, `schema_version: "1.0"`, `tutor_version`, echoed `message`, `reply`, and `sample: true`. This is explicitly not an AI explanation.

```sh
curl -fsS https://d1j3nkcez6kncs.cloudfront.net/api/v1/tutor/sample \
  -H 'Content-Type: application/json' \
  --data '{"message":"Hello TUTOR"}'
```

See `examples/tutor-sample.http` for a REST client request.

## Configuration and failure behavior

- `TUTOR_GRPC_TARGET=tutor.archreactor.internal:50051`
- `TUTOR_GRPC_TIMEOUT_SECONDS=5` (0.1-30 seconds)
- Empty target returns HTTP 503; there is no local fake-success fallback.
- Invalid input 422, resource exhaustion 429, unavailable 503, timeout 504, invalid upstream contract/other errors 502.
- Requests carry a generated UUID. BE verifies the returned UUID, echoed message, schema version, sample flag and response sizes.
- HTTP disconnect cancels the gRPC request. Automatic retries are disabled.
- New channel per request follows replacement task DNS, matching CORE's initial approach. DNS caches may briefly retain an old task address.

## Infrastructure

Blank Canvas account `242925688392`, Seoul `ap-northeast-2`. STS identity was verified before provisioning.

TUTOR owns `archreactor-tutor-build` and `archreactor-tutor-service` CloudFormation stacks, an ECR repository and CodeBuild project. Fargate uses 0.25 vCPU / 0.5 GiB and one task, with rolling replacement, gRPC health, non-root user, read-only root filesystem, and scoped image/log permissions. No application AWS role is needed by the sample.

Cloud Map uses the existing `archreactor.internal` namespace with a separate `tutor` registration. Only the BE security group can connect to TCP 50051. Public IPv4 is used for outbound HTTPS image pulls/logs without adding NAT or ALB. Internal transport is h2c without TLS/mTLS, matching CORE. Single task/AZ does not provide high availability.

TUTOR image-only deployment does not redeploy BE or CORE. See the TUTOR repository's `scripts/deploy.py` and infrastructure JSON templates. Maintain compatibility in v1; add separate v2 RPCs for breaking changes. Generated BE stubs have only their import path adjusted to `app.contracts.tutor_contract`.

The BE `TutorGrpcTarget` CloudFormation parameter configures the upstream. When updating this stack, set `ExistingApplicationVersion` from the current environment (or the intentionally newly deployed version) to avoid reverting newer application code.

## Verification

TUTOR tests cover a real gRPC round trip, health and invalid inputs. BE tests cover REST -> gRPC, contract mismatches, upstream errors, deadline and cancellation. CodeBuild runs tests and builds the images; the TUTOR build also starts a read-only container and calls its health and Sample RPCs.

CloudFormation templates pass cfn-lint and scoped cfn-guard rules. Change sets are reviewed before execution. The account currently has no configured CloudTrail trail; management event history is available but there is no durable trail retention. This work does not change audit logging.

## Deployment verification (2026-11-12)

- TUTOR CloudFormation `CREATE_COMPLETE`, ECS deployment `COMPLETED`, task `HEALTHY`.
- BE CloudFormation `UPDATE_COMPLETE`, environment `Ready / Green`.
- TUTOR image version: `tutor-a4e09bc31ce16f09`.
- BE version: `tutor-be-4b7662c8176e6c66`, built from base `1c60eb9` plus this integration.
- CodeBuild backend tests: 124 passed, 7 skipped. Local transport tests: 8 passed. TUTOR tests: 5 passed.
- Live HTTPS smoke: English and Korean requests returned HTTP 200 from TUTOR; four invalid requests returned HTTP 422.
- Run `python scripts/smoke-tutor-api.py` to repeat the public check.
- Prior BE version for rollback: `core-1c60eb9dcf49c72f4f6bc69bddba558eaba96c76-43142493712-1`. Set `ExistingApplicationVersion` to the chosen version through a reviewed change set. Keeping the added TUTOR settings is harmless to that older version.
- Public TUTOR source uses deployment parameters; actual account/resource names are only in its ignored local config. Its deployment script now requires `--config`.
