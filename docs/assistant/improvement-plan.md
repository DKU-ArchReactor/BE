# Assistant improvement plan

The 2026-11-13 smoke test submitted eight suggestions with synthetic built-in loop.c and a pipeline snapshot. One request failed without a diagnostic identifier; one answer was truncated. Later concise requests completed, but factual errors remained. This is a small, sequential conversation sample, not an accuracy benchmark. No conversation bodies or account information are retained here.

| Priority | Separate change | Acceptance criteria |
| --- | --- | --- |
| P1 | Answer brevity and evidence discipline | Default conclusion + 2–3 supporting points, roughly 500 Korean characters; explicit detailed requests remain supported. No invented identity, initialization history or optimization counts. |
| P1 | Frontend metric alignment | CPI, retired instructions, stalls and forwarding use the selected frame's server counters; repeated PCs count again; zero retirement has undefined CPI. |
| P1 | Request failure diagnostics | A safe server-generated reference identifies a failed request and its stage without logging prompts, source, account IDs, secrets or raw exceptions. Cancellation and quota behavior remain unchanged. |
| P2 | Suggestion UI (existing FE PR) | Eight emoji buttons in a single scrolling row; choosing a question never sends automatically. |

## Answer quality rollout gate

The system prompt now defaults to short answers, with an explicit detailed-answer exception. It distinguishes EX address calculation from MEM access, forbids deriving removable stalls/CPI gains from aggregate counters, treats absent forwarding as a per-cycle fact, and requires abstention on draft/execution identity. Hexadecimal byte examples correct the observed 32-versus-4 error. These are instructions, not mathematical verification or a guarantee that the model follows them.

Five synthetic machine-checkable regression cases live in `tests/fixtures/assistant_quality_cases.json`. With the existing approved runtime secret mechanism, run:

```sh
python -m scripts.evaluate_assistant_context --cases tests/fixtures/assistant_quality_cases.json
```

This is an opt-in paid/shared-quota model evaluation. It prints only labels, pass/fail and usage, not answers. Unit tests use fakes. Actual SOLID evaluation was run on 2026-11-13 against prompt commit `297fff0c85efdbd488604fa220f77aa5a4f6732a`: the rollout gate FAILED (9/15 factual passes, 1/16 valid natural-language questions incorrectly gated, and 14/15 ordinary model answers over 700 characters). See [evaluation findings and limitations](evaluations/2026-11-13-solid-quality.md). Hold rollout pending fixes and re-evaluation; PR UI readiness is not a quality approval.

Before rollout, require all five factual checks to pass in three independent conversations. Also ask all eight suggestions in fresh conversations and one sequential conversation; require no scope refusal for valid questions, no truncation, concise answers (target 500, review answers over 700 characters), and correct uncertainty. Test an explicit detailed request to ensure useful expansion. Review Korean prose manually: JSON extraction alone does not establish educational accuracy. Failed factual cases block rollout even if all requests return HTTP 200.

Deployment is separate. Capture model/version, prompt commit and aggregate pass/fail; never save raw user conversation or keys. If quality regresses, restore the previous prompt commit and keep the deterministic metric correction. Prompt constraints are probabilistic and cannot ensure 100% correctness.
