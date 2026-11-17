# Backend changes and frontend local integration

## Scope and status

Simulation trace storage in S3 is deferred. Existing assembly/ELF artifact storage and simulation JSON responses remain unchanged. No deployment was performed.

Implemented locally: owned build logs, static ELF disassembly and debug line mapping, bounded compiler execution, SOLID-compatible SSE transport adapter, and optional server-verified execution context for chat.

Pending: SOLID authentication startup wiring and a live response, actual RISC-V toolchain validation on Linux, and a separate compiler security boundary. Resource limits do not constitute a security sandbox. The current API and compiler still share a container/user.

## Responsibilities

CORE remains authoritative for executed instruction state, memory layout, hazards and `result.program.code_mapping`. The frontend already prefers that mapping in `translationCompile.ts`; keep this behavior. BE `analysis` is a static, pre-execution preview from the exact generated ELF, not a replacement for CORE runtime mapping. Do not merge mappings from different builds or source revisions.

## Compile response additions

`POST /api/v1/build/compile` keeps its existing request and response fields. RISC-V builds now include debug information (`-g`). New nullable fields:

- `analysis`: `disassembly`, `instructions`, `source_map`, `sections`, `mapping_available`.
- `analysis_error`: nonfatal inspection error. Build success does not imply inspection success.

Example analysis:

```json
{
  "instructions": [
    {"pc":"0x00010004","assembly":"li a0,1","source_line":2,"source_file":"source.c"}
  ],
  "source_map":{"2":["0x00010004"]},
  "sections":[{"name":".text","size":32,"address":"0x00010000"}],
  "mapping_available":true,
  "disassembly":"..."
}
```

Source line numbers are one-based; PC addresses are hexadecimal strings. Startup instructions have null `source_line`. Optimized-away lines can be absent; never invent a mapping or align instructions by array index. ASM-only builds may have no C mapping. Both guests and members receive analysis inline, without additional S3 writes.

## Saved build APIs

Both routes require the existing login authorization header and verify build ownership. Use a specific build ID; the previous objdump endpoint was unimplemented and its file_id-only signature did not identify an immutable build.

- `GET /api/v1/build/logs?build_id=<UUID>` returns `build_id`, `log`, `stdout`, `stderr`, `streams_available`. Historical rows retain combined `log`; separate streams are null and `streams_available=false`. Do not label combined historical output as stdout.
- `GET /api/v1/build/objdump?build_id=<UUID>` returns inline inspection data plus `build_id`, `file_id`. `assembly_url` is null; display `disassembly` directly. No new storage URL is created.

Missing build: 404. Other owner's build: 403. Failed build with no ELF: 409. Invalid ELF/inspection failure: 422. Download exceeding the ELF size limit: 413.

Apply Alembic revision `f281a64b209e` before running the new saved-build code. It adds nullable stdout/stderr columns without rewriting existing logs. Production startup already runs migrations; local integration must use its own local database.

## Chat and execution context

Existing text-only `POST /api/v1/assistant/chat` requests remain supported. An optional execution reference can be added:

```json
{
  "messages":[{"role":"user","content":"이 사이클에서 왜 스톨이 발생했나요?"}],
  "execution":{
    "build_id":"<saved-build-UUID>",
    "mode":"pipeline",
    "max_cycles":2000,
    "history_index":17
  }
}
```

This requires a logged-in owner and a saved successful build. It does not accept browser-provided trace objects or arbitrary artifact URLs. BE reads the owned ELF, reruns CORE, then supplies the summary and selected cycle to the model. `history_index` is zero-based and is not the CORE clock value.

**This is a rerun, not retrieval of the original displayed execution.** FE should label it accordingly. A CORE version change can change the trace. For exact original-run analysis, server-side execution retention is a separate future decision. Guest execution references are not supported in chat yet; guests still receive rule-based explanations from simulation responses.

A new SSE event precedes text when execution context is used:

```json
{"type":"context","kind":"server_rerun_not_original_execution","build_id":"...","execution_id":"...","core_version":"...","mode":"pipeline","history_index":17}
```

Continue handling `delta`, `done`, `error` and keepalive comments. Cancel the old request when the build/selection changes and ignore responses from superseded requests. Context exceeding 7,000 characters is rejected with 413; invalid selection or combined conversation limits produce 422. Context requests count against the existing allowance even if later validation or CORE fails.

## SOLID provider wiring

Configured endpoint: `https://dku-chat.kloud.zone/llm/v1/chat/completions`; model: `local/qwen3-coder-next`. `ASSISTANT_PROVIDER=solid` selects the adapter. `ASSISTANT_ENABLED` remains false by default.

The adapter accepts an application-owned authenticated `httpx.AsyncClient` through `HttpxTransport`, registered by `configure_transport` during application startup. The application's lifespan must close that client. No browser-supplied key or URL is accepted. Until this startup wiring exists, the configured provider is absent and chat returns 503.

Authentication wiring is intentionally pending: repository AGENTS.md requires loading `aws-secrets-manager` before credential work; that skill/retrieve tool is unavailable in the current environment. No keys were read, stored or requested. Complete the approved secret-resolution setup before activation; do not hardcode credentials into the startup code or frontend.

SSE compatibility was tested against mocked OpenAI-compatible frames. Actual server content type, terminal `[DONE]`, model availability and authentication still need a live test. Redirects are rejected and upstream error bodies are not forwarded to clients.

## Local verification checklist

1. Migrate only the local test DB and start BE with CORE configured.
2. Compile C at `-O0` and `-O2`, and ASM. Inspect analysis failures separately from compile failures. The machine must provide RISC-V gcc and objdump; Linux also requires prlimit.
3. Keep CORE mappings after simulation. Use static analysis only for pre-run preview.
4. Check new/historical build logs and reject another user's build.
5. Check syntax-error logs, invalid ELF, unmapped lines and expired guest simulation behavior.
6. Enable the authenticated SOLID transport after approved setup. Verify live text-only streaming, cancel, error and rate-limit paths.
7. Test saved-build context chat, wrong ownership and out-of-range history index. Confirm the UI labels the response as a rerun and discards stale answers.

## Compiler limits and remaining isolation

Compiler subprocesses now receive a minimal environment, have bounded captured output and a 10-second command timeout, and their process groups are terminated on completion or timeout. Linux uses prlimit for 512 MiB address space, 8 MiB per output file, 10 CPU seconds and 64 open file descriptors. `Dockerfile.prod` installs util-linux. These limits apply per command, not to the entire HTTP request, and must be validated in the Linux deployment image.

A dedicated compiler worker with no application credentials, no network access and a read-only filesystem remains a required architecture follow-up for stronger isolation. Do not expose a Docker daemon socket to the public API container to simulate this separation.


## Frontend implementation (2026-11-17)

The local frontend at `dist/FE` now displays the compile `analysis` before simulation completes, preserves CORE mapping priority, and shows inspection warnings separately from compile failures. The build status bar exposes inline logs and can reload saved-build logs with separate stdout/stderr or legacy combined output.

Compiling an unchanged saved C file uses `file_id`, producing an owned build eligible for context chat. Editing detaches that saved-file reference; save again before compiling if context chat is needed. Unsaved C and direct ASM compilation retain the existing guest/direct-input flow.

The assistant popup offers an execution-context checkbox only when a saved build has an actual selected history item. Single-mode step zero is synthetic and cannot be selected for AI context; later single steps map to `currentCycle - 1`. Responses are labelled as rerun analysis. Code, build, mode or selection changes cancel active chat and exclude earlier-context messages from subsequent requests. SOLID `stop` is treated as successful completion alongside Bedrock `end_turn`.

Verification: TypeScript/Vite production build, seven SSE/request-contract tests, and browser inspection of pre-execution mapping, logs and guest AI guidance against a temporary mock API. Real CORE/SOLID integration remains pending. The temporary mock was not deployed and is not a replacement for the real backend.

`dist/FE` is ignored by the backend repository. `patches/backend-integration-frontend.patch` is a cumulative patch against the local FE repository HEAD, including the prior uncommitted tutor/assistant work and this integration, plus test files. Apply it only to a matching clean FE base; do not apply it again to the already edited local checkout.
