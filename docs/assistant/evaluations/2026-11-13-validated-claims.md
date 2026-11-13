# Execution claim validation comparison

2026-11-13. Implementation is complete for this scoped change; **hold merge/deployment**. The server-rendered execution path improves factual reliability but does not make unrestricted educational explanations reliable.

## What changed

- Classify the latest question first. Only bounded, short referential turns receive prior user questions; generated assistant answers are excluded from classification. Scope decisions remain model-based and fail closed.
- For attached execution questions, build a server-owned fact catalog from validated counters, addresses, flags, allowlisted forwarding paths and fixed architecture rules. The model selects IDs; it cannot supply prose, labels or numerical values to the renderer.
- Validate a complete, bounded JSON selection before emitting a delta. The default selection is at most three facts; explicit JSON/detail requests allow eight. Keep one answer invocation, one quota reservation, existing cancellation/timeout and SSE contracts.
- Preserve free-form streaming for general/static code questions and unattached requests. This is an explicit protection boundary, not universal claim verification.

## Results

Same `local/qwen3-coder-next`, corrected synthetic loop/snapshot fixtures and comparison driver as the preceding PR evaluation. Each comparison arm has six factual questions repeated three times, eight fresh suggestions, eight sequential suggestions and one detailed request.

| Measure | Previous PR implementation | Current implementation |
| --- | --- | --- |
| Structured factual cases | 17/18 | 18/18 |
| Fresh + sequential suggestions admitted | 15/16 | 16/16 |
| Ordinary allowed answer mean | 597.9 characters (15 answers) | 268.3 characters (16 answers) |
| Ordinary answers over 700 characters | 2/15 | 0/16 |
| Complete/consistent execution reference | All admitted ordinary replies | All 16 ordinary replies |

Current ordinary replies include 12 server-rendered execution answers (mean 217.8 characters) and four free-form code/flow answers. All 12 validated with no empty/invalid-selection fallback. Median first-delta latency over the 16 ordinary replies was 0.520 seconds in this run; there is no comparable previous first-delta measurement or production SLA. The explicit detailed answer was 611 characters, but its table still contained a static step-label error.

The 35-request final comparison reported classification 55,735 + answer 35,935 = 91,670 tokens. These are provider-reported counts, not a billing reconciliation. Direct synthetic evaluations consume SOLID shared quota, not application user reservations.

Independent classification: **44/44**, including the existing 38 cases plus six poisoned-assistant-history, short follow-up, English follow-up, mixed and unrelated cases. No false allows, false blocks or transport failures in those 44.

Additional execution cases: **2/3**. A named-register question (`x10의`) and a positive MEM/WB→rs1 forwarding-path question passed. A question asking unknown `has_stall/has_forwarded/has_flush` values was incorrectly **CLARIFY**, so no answer call occurred. A small field-glossary experiment did not fix it and was removed. Do not describe the combined evaluation as having zero false blocks.

## Manual review and remaining release blockers

- In the server-rendered hazard replies, no-forwarding is correctly limited to the selected cycle, address calculation is EX and memory access is MEM, load-use can still stall with forwarding, and removable stalls/improved CPI remain unknown without comparative execution.
- Identity/history replies do not invent completed iterations or prove draft/run identity. Unknown event flags remain unknown in unit tests, rather than being converted to false.
- One **free-form code reply** said the sum returned 5, then corrected itself to 10 in the same answer. Free-form replies also incorrectly described an attachment as absent or suggested a completed snapshot alone was sufficient to establish history. A detailed static table merged initialization with an iteration. These are unresolved educational-quality errors.
- One mapping request still selected unnecessary CPI/hazard topics and included a valid but irrelevant forwarding rule. IDs establish provenance, not relevance or completeness.
- Free-form answers without execution attachments, generic concept questions, and static code explanations are not forced through claim validation. A topic-selection mistake can route a question to that path. The model can still give incorrect prose there.
- Execution explanations have less freedom: source-to-instruction mapping and arbitrary register-transition explanations are not reconstructed. They use a narrow fact catalog and may request additional data even when raw tutor text exists. This tradeoff must be reviewed before enabling the change.
- The evidence is a small synthetic sample, not a universal accuracy or safety guarantee. Server calculations do not prove the simulator data itself is correct.

## Regression and reproducibility

Local related tests: **226 passed**, one existing Pydantic deprecation warning. Tests cover authentication/quota, SSE, timeouts/cancellation during buffered validation, closed upstream clients/released slots, schema on/off, malicious/unknown/duplicate selections, unknown flags, positive forwarding paths, numeric validation, Korean-suffixed ABI names and metadata-only logging.

Final comparison metadata records answer/classifier/claim-prompt and fixture hashes. The final source also contains deterministic fixes for Korean register suffixes, complete ABI aliases and empty-memory catalogs; these were verified with unit tests and the additional live named-register case. The comparison's original 35 inputs do not depend on those changes.

Intermediate attempts are retained in the aggregate metadata: without JSON Schema, only 12/18 facts passed and 9/16 ordinary replies fell back. The model often selected field paths instead of fact IDs. Applying the gateway's supported JSON Schema yielded 6/6 in the pilot and 18/18 in the final comparison; server validation remains mandatory even with schema support. This is **system-level answer construction**, not proof the underlying model's reasoning became 100% accurate.

Artifacts:
- `tests/fixtures/assistant_quality_cases.json`: unchanged corrected six-case fixture.
- `tests/fixtures/assistant_followup_cases.json`: six added classification cases.
- `tests/fixtures/assistant_claim_cases.json`: named register, positive forwarding path and missing-event cases (last case currently fails live classification).
- `2026-11-13-validated-claims.json`: final comparison, domain and extra-case metadata plus failed pilots; no answer bodies.

Reproduce the comparison with `scripts/compare_assistant_quality.py --source-root <checkout> --arm <name> --output <metadata.json>`. Evaluate the extra fixture with `python -m scripts.evaluate_assistant_context --cases tests/fixtures/assistant_claim_cases.json`. For the 44-case domain run, concatenate the domain and follow-up fixture lists and pass them to `scripts.evaluate_assistant_domain.evaluate` in an approved credential environment. No production user data or secret values are evaluation inputs/outputs.

Frontend handoff: request body and event names are unchanged. An execution reply may arrive as one validated delta followed by done. Keep loading through connected/keepalive; stop on done/error and retain disconnect cancellation. `done.context` and `done.usage` keep their existing meanings. No frontend edits, PR merge, deployment or production database changes were performed.
