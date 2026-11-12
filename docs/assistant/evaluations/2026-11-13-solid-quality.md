# SOLID answer-quality evaluation — 2026-11-13

**Recommendation: hold PR #14 rollout.** The changed prompt does not reliably meet the brevity or factual-grounding gate. Returning a complete answer is not evidence of accuracy.

## Evaluated configuration

- Prompt commit: `297fff0c85efdbd488604fa220f77aa5a4f6732a` (PR #14).
- Actual SOLID endpoint: `https://dku-chat.kloud.zone/llm/v1`; model identifier: `local/qwen3-coder-next`. The service does not pin an immutable model revision here.
- Normal `TopicClassifier` → `GuardedProvider` → `SolidLLMProvider`, 60-second total deadline, 2,048 answer-token ceiling. No prompt monkeypatch or mock model.
- 32 requests: five factual cases repeated in three independent rounds; eight suggestions each in a fresh conversation; the same eight in one sequential conversation; one explicit detailed-answer request. 32 classification calls and 31 answer calls (one CLARIFY).
- Backend prompt isolated from the FE brevity suffix: suggestion text came from `codex/assistant-compile-hint` but `BRIEF_ANSWER_REQUEST` was not appended. This is not a deployed frontend end-to-end test.
- Synthetic C loop and selected pipeline snapshot only. Secrets were resolved at runtime via the approved `asm-exec` mechanism. No user conversations, source files, keys, or raw answer bodies are retained in the report/metadata.
- No deployment, merge, application/DB mutation, or route quota test. Direct provider evaluation consumes SOLID quota but does not reserve an application-user chat allowance.

## Factual gate

The unchanged `tests/fixtures/assistant_quality_cases.json` was passed to `scripts.evaluate_assistant_context`. Each request started a fresh conversation.

| Case | Round 1 | Round 2 | Round 3 |
| --- | --- | --- | --- |
| Stack byte arithmetic | Pass | Pass | JSON parse failure |
| Load-use / EX address calculation / no invented savings | Pass | Pass | Pass |
| Draft/execution identity | JSON parse failure | JSON parse failure | JSON parse failure |
| Selected CPI (26 / 13 = 2.0) | Pass | JSON parse failure | Pass |
| Unknown past iterations / initialization | Pass | **Incorrect facts** | Pass |

**9/15 machine-checkable passes**, versus the required 15/15. Five failures are JSON parsing failures, not proven factual errors: the evaluator could not extract a valid object. One valid JSON answer incorrectly supplied an integer iteration count and a boolean initialization state where evidence requires `null`. Do not report this as a 60% general model-accuracy score.

Two evaluation limitations need correction before the next gate:

1. The synthetic factual fixture inherited an inconsistent final summary (zero final stalls/forwards despite one selected cumulative stall and seven forwards). The original gate was run unchanged and the inconsistency is disclosed. Natural-language evaluation **omitted `whole_run_summary`**, rather than inventing a corrected final trace. Add a separate deliberately inconsistent-data case with an explicit abstention expectation.
2. Completion, answer usage and reference checks are currently recorded after JSON parsing. Those fields are unavailable for the five parse failures; their truncation status and full token totals must not be inferred. Record transport completion/usage before parsing in the next evaluator revision. An enforced first prose sentence for identity questions also competes with JSON-only requests; treat content and formatting checks separately.

## Natural-language evaluation

Eight suggestions used the same selected snapshot (`cycle=25`, elapsed 26, 13 completed instructions, CPI 2.0, load-use stall, no forwarding/flush in that cycle), an unverified C draft, empty instruction/tutor arrays, and no whole-run summary. Missing evidence is intentional: the assistant should distinguish static analysis from observed execution and ask for absent instruction history.

| Suggestion | Fresh / sequential characters | Manual findings |
| --- | ---: | --- |
| Code explanation | 1,242 / 798 | Static sum 10 is correct, but `x17=10` was treated as a return-value source and the execution was linked to the draft without evidence. Sequential answer called selected elapsed cycles the complete execution length. |
| C/ASM mapping | 883 / 986 | Fresh answer suggested `addi x0, x0, 0` for variable initialization; this does not initialize a variable. Sequential answer invented the variable location and treated x17 as observed return-value evidence. |
| Register changes | 1,188 / 802 | Asked for missing ASM, but also speculated about variable/register roles and initialization. Fresh answer associated `0x0001023c` with decimal return value 10. |
| Branch/loop | 858 / 816 | Claimed four iterations had actually completed despite no history and `not_verified`; fresh answer later contradicted itself by saying this cannot be confirmed. |
| Stack | 788 / 730 | Fresh answer calculated the address difference as 20 bytes; correct difference is 32. Sequential arithmetic was correct but called s0 caller-saved and inferred a frame size from addresses alone. |
| Hazards | 375 / 755 | Fresh answer correctly read stall/forwarding/flush flags. Sequential answer invented the specific lw→add pair and incorrectly explained CPI 2.0 as one baseline cycle plus one stall per instruction. |
| CPI | 828 / 806 | Both obtained selected CPI 2.0. Fresh answer asserted whole-run CPI also equals 2.0 solely from COMPLETED status. Sequential answer equated forwarding count with removed stalls and invented an improved CPI of 15/13. |
| Code/run comparison | 889 / 122 | Fresh answer started with the correct uncertainty, then wrongly used C-source-vs-ELF hash differences to prove different binaries. Sequential request was **CLARIFY**, an erroneous gate outcome for this explicit in-domain question; its 122-character response is a fixed notice, not an answer. |

- Fresh: 8/8 ALLOW; sequential: 7/8 ALLOW and 1/8 CLARIFY.
- All 15 allowed ordinary answers ended with `end_turn` and matching context reference; no truncation or provider exception was observed in this natural-language sample. The CLARIFY notice correctly did not call the answer model or attach an answer context.
- Ordinary model answers: **mean 849.6 characters**, median 816, range 375–1,242; **14/15 exceed the 700-character review threshold**. Fixed notice and explicit-detail response excluded. Counts include Markdown and whitespace.
- Median classification-plus-answer elapsed time: 3.25 seconds fresh, 3.29 seconds sequential (small local sample, not an SLA).
- Manual review found substantive technical or grounding problems in 14/15 ordinary model answers; the fresh hazard answer was the only one without such a problem. This review is qualitative, one reviewer, one synthetic context, and must not be generalized as production accuracy.
- Explicit detailed request: ALLOW, `end_turn`, 1,132 characters. The table correctly traced sum 0→1→3→6→10 and i=5 at exit. Expansion worked, though spelling and claims about what future attachments could prove still need review.
- Natural-language evaluation including the detailed request: classification 30,926 input / 104 output tokens; answers 75,578 input / 7,860 output tokens. Total 114,468 reported tokens. **This excludes all 15 factual requests** and is not a price estimate. Partial factual telemetry cannot support an exact full-run total.

Sequential responses repeated earlier unsupported claims. A correct disclaimer at the start or end did not prevent contradictory claims in the body. No paired baseline with the same fixtures was run, so this is not a measured before/after improvement result.

## Required next changes

1. **Separate static code explanation from observed execution evidence.** Use question-specific context selection and explicit missing-evidence indicators; unrelated register/memory values currently encourage invented variable mappings. Preserve the ability to answer execution questions with their relevant evidence.
2. **Use deterministic calculations for addresses and metrics.** Supply checked byte differences/CPI operands; avoid relying on the model for arithmetic or declaring savings from event counts. Do not confuse a selected snapshot with the final frame merely because the run is complete.
3. **Shorten the instruction set and test adherence.** Default to one conclusion plus two or three short points; allow detail on explicit request. Avoid competing formatting instructions and verify the service/model's system-instruction behavior. Do not lower token limits just to cut answers off.
4. **Fix classification regression in long conversations.** Give the latest explicit question priority; add the sequential comparison case without letting previous model guesses redefine the question's topic.
5. **Correct and broaden the evaluator.** Fix the unintended fixture inconsistency, retain deliberate inconsistent-evidence cases, capture completion before parsing, and repeat the gate across different codes/cycles. Include generic ABI mistakes, source-vs-artifact identity, and conversation-error propagation in manual review.

These are follow-up recommendations, not changes deployed by this evaluation. Keep rollout blocked until the repeated factual and natural-language gates pass. Prompt restrictions remain probabilistic and cannot ensure 100% correctness.

Aggregate metadata: [2026-11-13-solid-quality.json](2026-11-13-solid-quality.json).
