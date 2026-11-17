# Backend changes and frontend local integration

## Scope and status

Simulation trace storage in S3 is deferred. Existing assembly/ELF artifact storage and simulation JSON responses remain unchanged. No deployment was performed.

Implemented locally: owned build logs, static ELF disassembly and debug line mapping, bounded compiler execution, integration with the existing core SOLID provider and server-owned execution snapshots.

Pending: live SOLID/CORE integration verification, actual RISC-V toolchain validation on Linux, and a separate compiler security boundary. Resource limits do not constitute a security sandbox. The current API and compiler still share a container/user.

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

The latest `core` assistant implementation is authoritative. This PR does not replace its SOLID provider, domain checks, request diagnostics, editor-source support, or immutable execution snapshots.

For logged-in saved-build runs, FE sends `capture_assistant_context: true` to `/api/v1/simulation/run`. It preserves the returned `assistant_context` descriptor alongside that exact mode's result. Chat sends `context` (not the retired `execution` field):

```json
{"messages":[{"role":"user","content":"Explain this cycle"}],"context":{"execution_id":"<UUID>","result_version":"<64 hex chars>","artifact_sha256":"<64 hex chars>","mode":"pipeline","cycle":0,"memory_addresses":[]}}
```

`cycle` is the zero-based CORE history index; single-mode synthetic step zero has no context. This references the original stored execution, not a rerun. FE checks descriptor availability, mode, selected range and expiration. BE remains authoritative for ownership, expiry and version checks. Changing source, build, mode, execution ID or cycle cancels active chat and excludes older-context dialogue.

The existing core SOLID configuration and application lifecycle are preserved. Actual authenticated SOLID responses and full FE/CORE integration remain to be tested. No secrets or deployment settings were changed during conflict resolution.

## Local verification checklist

1. Apply migrations to a disposable database: the new build-stream revision follows `f821a73d9001` (execution snapshots). Both tables and stream columns must exist.
2. Use RISC-V GCC and objdump on Linux; retain core's single ELF compilation pass and `-gdwarf-4`. Inspect C at -O0/-O2 and ASM. Analysis failure is nonfatal.
3. Verify static preview before execution and CORE mapping priority afterward.
4. Verify separate/legacy logs and ownership denial.
5. Exercise saved-file compile, both simulation modes and snapshot-context chat against real services; verify expiry/mismatch errors and cancellation.

## Compiler limits and remaining isolation

Compiler subprocesses now receive a minimal environment, have bounded captured output and a 10-second command timeout, and their process groups are terminated on completion or timeout. Linux uses prlimit for 512 MiB address space, 8 MiB per output file, 10 CPU seconds and 64 open file descriptors. `Dockerfile.prod` installs util-linux. These limits apply per command, not to the entire HTTP request, and must be validated in the Linux deployment image.

A dedicated compiler worker with no application credentials, no network access and a read-only filesystem remains a required architecture follow-up for stronger isolation. Do not expose a Docker daemon socket to the public API container to simulate this separation.


## Frontend implementation

The companion FE PR displays build status, inline/saved logs and static analysis before simulation completes. CORE runtime mappings take precedence. Unchanged saved C files compile with `file_id`; editing detaches that reference until the file is saved again.

The execution-context checkbox uses the stored snapshot descriptor returned by the corresponding simulation result. UI copy identifies it as stored execution analysis. Missing, expired or mismatched descriptors fall back to text-only questions. Backend context errors are shown to the user.

Frontend source is maintained in the separate FE repository/PR; the old local cumulative patch is not the integration source of truth.
