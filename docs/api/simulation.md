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

## CORE service setup

Use the CORE `feat/simulation-grpc-api` change (targeting CORE `develop`), which
adds `server.grpc_server` and `Dockerfile.server`. Pin the reviewed CORE commit
for builds. The previous public CORE `main` does not contain this server or the
new single engine. The separate historical `dist/CORE` mentioned in AWS docs is
not a dependency or source of truth for this implementation.

1. In CORE, install `requirements-server.txt` and run `python -m server.grpc_server`.
2. In the BE process set `CORE_GRPC_TARGET=127.0.0.1:50051` (or the private CORE address).
3. Install BE dependencies and start the existing `uvicorn app.main:app` service.
4. Use an owned saved build or an anonymous RV32IM compile token to call `/run`.

The server handles `SINGLE` and `PIPELINE` over the existing protobuf contract.
No new `/single` endpoint, DB migration, FE modification, or deployment is needed
to review this API patch. Running a deployed integration still requires the new
CORE service and the existing database/storage configuration.

## Local integration tests

From this BE checkout, using one environment containing BE test dependencies and
CORE server runtime dependencies:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -r ../CORE/requirements-server.txt
$env:DEBUG = 'false'
$env:CORE_SOURCE = (Resolve-Path ../CORE).Path
python -m pytest -q -rs
```

The tests start a real CORE gRPC server subprocess from `CORE_SOURCE` and exercise
FastAPI routing, the BE client, worker execution, mode/status mapping, and full
result preservation. S3 downloads/DB ownership lookups use local boundary stubs;
anonymous auth rules are also covered by existing tests. Reference ELF execution
is real. `program2.elf` completes 97 instructions in single 97 clocks / pipeline
134 clocks, with matching final registers, memory, and console output.

When `CORE_SOURCE` is absent, cross-repository tests explicitly skip. GCC/RISC-V
compiler and PostgreSQL tests require their respective tools/`TEST_DATABASE_URL`.
Docker image builds and live AWS/S3/DB/FE behavior are separate validation; no
production deployment has been performed by this patch.
