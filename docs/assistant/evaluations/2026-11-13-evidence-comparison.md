# Evidence-selection implementation and live comparison

**2026-11-13 — implementation complete; rollout gate still not met.** Shorter answers and more reliable structured facts are measurable in this sample, but free-form explanations still contain serious errors. Do not merge/deploy on the strength of 17/18 factual passes alone.

## Implemented scope

- Corrected the unintended selected/final-summary contradiction in the synthetic fixture; added a deliberately inconsistent CPI case with an explicit abstention expectation.
- Evaluation captures completion, usage and context reference before parsing facts. Classification, transport, truncation, format and factual failures are distinguished.
- The existing classifier call returns a validated internal topic list alongside its decision. No extra model call, client field or quota reservation was added. Invalid/unknown/duplicate topics fail closed.
- Projection sends topic-specific execution fields and bounded dialogue data. Static-only topics omit execution clocks and register values; hashes are omitted from model evidence to avoid source-vs-ELF comparisons. Mixed topics use the allowlisted union.
- Classifier receives only editor language/character count, not the separately attached source content. Relevant allowed answers still receive the original source. User-pasted code inside the question remains part of the question.
- Server verifies selected/final CPI separately, missing/zero/inconsistent counters, and bounded RV32 byte arithmetic. No arbitrary expression evaluation or new memory reads.
- One concise answer policy replaces the unused older prompt sections. Explicit detailed/JSON requests remain supported. No automatic full-run analysis, frontend changes, deployment or DB modification.

Implementation/FE handoff: [evidence-selection.md](../evidence-selection.md).

## Comparison method

Model: `local/qwen3-coder-next` at the configured SOLID gateway. This identifier is not an immutable model revision. Each source version was imported in a separate process with the same fixtures and evaluator. No mocks or user conversation inputs. Runtime secret resolution used `asm-exec`; secret values were not read into the agent context or saved.

| Arm | Source | Factual pass / 18 | Valid prose questions allowed / 16 | Mean ordinary-answer chars | Answers >700 | Median answer elapsed seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Before PR #14 | `c21f7ab` | 6 | 15 | 3,081.5 | 15/15 | 10.334 |
| Previous PR #14 | `297fff0` | 11 | 16 | 1,293.4 | 14/16 | 5.005 |
| Final implementation | `d2a7b60` | **17** | **15** | **597.9** | **2/15** | **2.256** |

Six factual cases × three independent conversations per arm, eight suggestions separately and in one sequential conversation, and one detailed request: 35 requests per primary arm. The FE brief-answer suffix was excluded. The final ordinary answers ranged from 417–941 characters. Fixed notices and detailed answers are excluded from length means. All allowed ordinary answers in these arms ended with `end_turn`; no truncation or transport error was observed. All returned context references matched.

The original baseline exceeded the 24,000-character history budget once, so the oldest user/assistant pair was removed and this event was recorded. Consequently the final sequential history is not identical across arms. Current implementation also intentionally bounds model history to six messages / 4,000 characters. These are system-level comparisons, not a pure prompt-only ablation. Model answer temperature was left at the provider default in all arms; classification uses temperature 0. Token ceiling stayed 2,048 for answers; topic classification has a 256-token ceiling versus the earlier 128.

Reported tokens for each full 35-request arm:

| Arm | Classification tokens | Answer tokens | Total |
| --- | ---: | ---: | ---: |
| Before PR #14 | 53,910 | 181,445 | 235,355 |
| Previous PR #14 | 54,530 | 182,433 | 236,963 |
| Final | 56,342 | 74,809 | 131,151 |

This is observed usage, not a billing estimate or latency SLA. The final run started near completion of the separate domain evaluation. Service load and sampling can vary; one small fixture cannot establish production accuracy.

## Final factual results

| Case | Result across three runs |
| --- | --- |
| Address difference and s0-20 | 3/3 |
| Load-use with forwarding / EX address calculation / unknown savings | **2/3** |
| Draft/execution identity | 3/3 |
| Selected CPI | 3/3 |
| No evidence for past iterations / initialization | 3/3 |
| Deliberately contradictory CPI | 3/3 |

The one failure returned the wrong boolean for whether a load-use stall can remain necessary with forwarding. It was a valid complete JSON answer, not a parser failure. The final independent domain set passed **38/38** (20 allowed, 18 non-allowed, no false blocks/allows or errors), but the real sequential button dialogue still produced one erroneous **CLARIFY** for code/run comparison. Do not collapse these separate evaluations into a claim that no false blocks remain.

## Manual prose review: remaining blockers

- **Code explanation:** a sequential answer invented that two iterations had finished, despite absent execution history. A fresh answer treated metrics `status=verified` as execution completion.
- **C/ASM mapping:** a fresh answer again used `addi x0,x0,0` as variable initialization and included RV64 `sd` in an RV32IM explanation.
- **Registers:** a sequential answer misread x10 as zero and treated x17=10 as a return value; neither claim was supported.
- **Stack:** address arithmetic stayed 32 bytes, but frame size, variable allocation and frame-pointer use were still inferred from it. The sequential answer exceeded 700 characters.
- **Hazards/CPI:** the model interpreted a single-cycle `has_forwarded=false` as disabled forwarding and claimed enabling it would remove the load-use stall. It proposed an unsupported improved CPI of about 25/13. Server-checked current CPI does not validate these causal/optimization claims.
- **Identity:** the fresh answer withheld identity correctly; the sequential one was incorrectly gated. Some explanations still overpromise what an ASM attachment alone proves.
- **Static flow:** uncertainty improved, but some answers under-explain the statically knowable iteration count and request execution material unnecessarily. Mixed-language terms and awkward Korean remain.
- **Detailed request:** expanded to 1,194 characters and reached the correct 0→1→3→6→10 progression, but started with a malformed/incorrect table before correcting it. Treat useful expansion separately from presentation quality.

These observations are qualitative review of synthetic outputs. Full answer bodies and user data are not stored in repository metadata. We do not assign a general natural-language accuracy percentage.

## Intermediate experiments and limitations

The whole task issued 219 logical evaluation requests including tuning runs (not 219 application-user chat requests): an initial six-case smoke, two 35-request intermediate variants, the three 35-request primary arms and 38 classification-only domain cases. No app-user daily allowance was reserved; SOLID shared quota was consumed.

- Initial smoke passed 5/6 with a forwarding error.
- `8f4fecb` then passed 18/18 structured facts, but prose hallucinations and topic over-selection remained.
- `1468f12` reduced prose lengths further but regressed to 11/18 facts due mostly to classification, and allowed only 13/16 ordinary questions. This variant was not chosen.
- Final `d2a7b60` restores the established classification rules while retaining internal topics and evidence projection. Failures from earlier trials are preserved in aggregate metadata rather than omitted from the report.

Tests and examples informed prompt revisions. This is not a held-out benchmark, and the selected snapshot intentionally lacks instruction/tutor history. Before rollout, evaluate different real simulator-derived snapshots with populated instruction/tutor evidence as well as absent/inconsistent data. Current routing is probabilistic and can still select unrelated allowed topics (for example cpi during code explanation).

## Validation and next decision

- **188 local tests passed**: domain/SOLID transport, schema boundaries, selected execution ownership/version checks, SSE, single quota reservation, cancellation/timeouts, projection, arithmetic and evaluator behavior. Existing Pydantic configuration deprecation warning only.
- No merge, deployment, frontend modification, DB schema change or user-data mutation.
- Rollout gate remains blocked by the final factual failure, sequential false block and unsupported prose claims. The next quality work should isolate prior assistant claims from evidence more strongly, evaluate stricter evidence/answer schemas or another available model, and validate on richer simulator cases. Merely adding more prompt sentences has not eliminated the errors.

Aggregate evidence, prompt hashes, per-case outcomes and token counts: [comparison metadata](2026-11-13-evidence-comparison.json).
