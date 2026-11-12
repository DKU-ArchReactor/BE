# Assistant answer quality follow-up

Observed issues: CPI was expanded as Instructions Per Clock, incomplete execution was treated as uncomputable, and absent context led to requests for internal JSON plus invented hazard terminology.

The curated answer guide now distinguishes CPI/IPC and selected-cycle/whole-run metrics, supplies the actual execution-attachment workflow, and requires event evidence for stall, forwarding and flush claims. Editor source is still not automatically sent. Domain classification, request schemas, quota and SSE contracts are unchanged.

Four additional opt-in SOLID evaluation cases cover CPI/IPC correction, missing-context UI guidance, editor visibility and hazard uncertainty. Run `python -m scripts.evaluate_assistant_context` with the existing approved runtime credential path. Local mocked tests only verify integration; they do not establish model accuracy. The new guide still needs actual model evaluation before release. Prompt instructions reduce errors but do not guarantee factual correctness or perfect policy enforcement.

Frontend changes are in FE PR #18: Markdown/math rendering, attachment instructions and a per-question attachment indicator. The new backend guide must be deployed separately to affect actual SOLID answers; this change does not deploy or merge anything.
