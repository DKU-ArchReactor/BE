# Simulation API integration

## Endpoint and request

Keep the existing `POST /api/v1/simulation/run` endpoint and HTTP 200 response
convention. `app/schemas/simulation.py` owns the Pydantic models, the router owns
HTTP/auth/storage orchestration, and `app/services/simulation_service.py` owns
the transport-only gRPC client. BE does not import CORE implementation modules.

```json
{
  "build_id": "owned-successful-build-UUID",
  "mode": "single",
  "max_cycles": 2000
}
```

Alternatively use `simulation_token` from the anonymous compile response and
omit `build_id`. Exactly one artifact identifier is required. Saved builds
require login and ownership; anonymous tokens retain their existing expiration
and authorization rules. `mode` is `single` or `pipeline` (default `pipeline`),
and `max_cycles` is a JSON integer 1–2000 (default 2000).

The build API remains `POST /api/v1/build/compile`, with `compile_profile=rv32im`.
Compile success must be checked from its JSON `status`, not HTTP 201 alone.

## Response

The existing envelope is preserved:

```json
{
  "request_id": "correlation ID",
  "execution_id": "CORE execution ID",
  "execution_status": "COMPLETED",
  "core_version": "CORE source commit or development",
  "result_schema_version": "1.0",
  "result": {
    "schema_version": "1.0",
    "status": "halted",
    "simulator": {},
    "program": {},
    "initial_state": {},
    "summary": {},
    "history": [],
    "console_output": ""
  }
}
```

The inner example only illustrates structure; actual metadata/counters/history
come from CORE. The typed envelope preserves the inner dictionary and additional
CORE fields. `initial_state`, program fingerprint/instructions/ELF regions and
all per-cycle data survive transport unchanged. `Server-Timing` remains available.

| Outcome | HTTP | `execution_status` |
|---|---|---|
| Successful program | 200 | `COMPLETED` |
| Program reaches clock limit | 200 | `CYCLE_LIMIT` |
| Simulated runtime fault | 200 | `SIMULATION_ERROR` |

Malformed input/unsupported ELF is 422; existing authentication/ownership rules
return 401/403, expired anonymous tokens 410, oversized ELF 413, CORE resource
limits 429, unavailable CORE 503, deadline 504, and invalid/upstream-contract
responses 502. Errors use FastAPI's existing `{"detail": "..."}` format.

The client rejects mismatched response modes/clock limits, legacy serialized
pipeline-style single results, incompatible schema majors, contradictory status
or history counts, and non-finite JSON constants. It does not reinterpret a
pipeline result as single mode.

## Existing CORE service

Reuse the deployed `archreactor.v1` service and its existing BE connection
(`CORE_GRPC_TARGET`). Both `SINGLE` and `PIPELINE` already work over this contract.
No separate single-cycle gRPC service or new `/single` HTTP endpoint is required.

On 2026-11-05 the existing public API compiled `int main(void) { return 42; }`
and successfully ran the same ELF in both modes. Both returned HTTP 200 and
`COMPLETED`, a0=42, and 14 retired instructions. The existing engine used 88
single clocks / 25 pipeline clocks. Each complete `result` dictionary exactly
matched a direct run of the documented baseline engine `1bf2957`. The deployed
version reported `core-1bf2957eb2d6-7b39acaa099a3b65`.

The new engine in CORE `develop` preserves `create_state(..., mode=...)`,
`run_simulation`, and `delete_state`. Update those engine files within the
existing service's build/deployment, preserving its transport and controls.
The separate server implementation in CORE PR #5 was closed as redundant.

The original service source/build package was not recovered locally, and the
required AWS profile was unavailable for inspecting its image/source archive.
The operational API probe verifies existing behavior, not the new engine's
deployment. Recover that service's original build source before updating it;
do not replace its adapter on the assumption that the public engine repo is a
complete snapshot of the deployed container. CORE `main` still excludes the new
engine; pin a reviewed `develop` commit when preparing the update.

Existing DB, S3, authentication and private network configuration remain in use.

## Local integration tests

From this BE checkout, using one environment containing BE test dependencies and
the real CORE engine's test dependency:

```powershell
python -m pip install -r requirements-dev.txt
$env:DEBUG = 'false'
$env:CORE_SOURCE = (Resolve-Path ../CORE).Path
python -m pytest -q -rs
```

The tests start `tests/helpers/core_rpc_fixture.py`, a test-only RPC fixture
around actual engine execution from `CORE_SOURCE`. It is not a production CORE
server and must not be deployed. This exercises FastAPI routing, the BE client,
the unchanged wire contract, actual engine execution, mode/status mapping, and
full result preservation. S3 downloads/DB ownership lookups use local boundary
stubs; anonymous auth rules are covered by existing tests. The fixture works
with CORE `develop` alone, without CORE PR #5. `program2.elf` completes 97
instructions in single 97 clocks / pipeline 134 clocks, with matching final
registers, memory, and console output.

When `CORE_SOURCE` is absent, cross-repository tests explicitly skip. GCC/RISC-V
compiler and PostgreSQL tests require their respective tools/`TEST_DATABASE_URL`.
Docker image builds and live AWS/S3/DB/FE behavior are separate validation; no
production deployment has been performed by this patch.
