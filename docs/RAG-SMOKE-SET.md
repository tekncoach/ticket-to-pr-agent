# RAG smoke set — Day 4's last task

10 queries against the real 303-chunk corpus (5 answerable / 3 unanswerable / 2 multi-hop), hit@6 and citation accuracy recorded by hand, against the live agent (`agent.factory.build_runtime()`), not just `search_kb()` in isolation — Day 4's own deliverable is "citation-enforced answers," not raw retrieval.

## The queries and what they found

| # | Type | Query | Retrieval hit@6 | Agent result (before fix) |
|---|---|---|---|---|
| A1 | Answerable | Why betterleaks instead of detect-secrets? | ✅ SECRETS-REDACTION fills top 4 | **FAIL** — never called `search_kb`, wandered `bash`/`edit_file` for 8 turns, hit `max_turns`, no answer at all |
| A2 | Answerable | The eleven domains a production agentic system needs? | ✅ checklist-agents-production top 2 | Correct + honest hedge on the ambiguous 11th item, but cited `[source#chunk_id]` literally instead of the real citation |
| A3 | Answerable | % of engineers who never use agent mode (DORA)? | ✅ dora sources present | Correct (61%), cited cleanly |
| A4 | Answerable | This project's north-star SLO? | ❌ **the actual SLOs chunk (`SPEC#9.0`) absent from top 6** | **FAIL** — confidently answered from the wrong chunk (`SPEC#11.0`, Deferred architecture decisions) as if it were the SLO, no hedge |
| A5 | Answerable | Benchmarks report's mergeability-vs-completion gap? | ✅ sota-benchmarks fills all 6 | Correct (42.3% vs 81.5%), but same literal `[source#...]` citation bug as A2 |
| U1 | Unanswerable | Boiling point of tungsten? | scores overlap with real hits (see below) | Refused correctly in spirit, but never called `search_kb` and never emitted the specified `INSUFFICIENT_CONTEXT` format |
| U2 | Unanswerable | Ibuprofen adult dosage? | same | same as U1 |
| U3 | Unanswerable | Which vector DB does Pinecone recommend at scale? | same | same as U1 |
| M1 | Multi-hop | This project's CI SLO vs. SOTA mergeability rate? | ✅ (both sub-topics present) | **FAIL** — same `bash`/`edit_file` wandering as A1, `max_turns`, no answer |
| M2 | Multi-hop | DORA on code review vs. Singh's acceptance criteria? | ⚠️ a single combined query misses Singh entirely; the agent's own two separate `search_kb` calls found both | **Pass** — genuine synthesis, both sources cited correctly |

**Citation accuracy, before fix:** 3 of 7 answered queries cited correctly (A3, and M2's two citations); 2 used a literal `[source#chunk_id]` placeholder instead of the real citation (A2, A5); 1 cited the wrong chunk with full confidence (A4); 2 never produced an answer at all (A1, M1).

## Two fixes applied and re-verified live, not just reasoned about

1. **`bash`/`edit_file` wandering instead of calling `search_kb` (A1, M1).** `SYSTEM_PROMPT` never said `search_kb` was the *only* way to reach the knowledge base — for a question like "why X instead of Y," the model sometimes tried to find the answer by exploring the target repo's files instead. Fixed by stating explicitly that `bash`/`edit_file` only ever see the target repo's own code, never the knowledge base, and that `search_kb` is the one way to reach it. Re-verified live: A1 and M1 now call `search_kb` directly (1-2 calls) and answer correctly, no `max_turns`.
2. **Literal `[source#chunk_id]` citations (A2, A5) instead of the tool's real `citation` field.** `GROUNDING`'s own instruction text ("cite `[source#chunk_id]`") reads as a copyable template, and the model sometimes copied it verbatim instead of substituting the actual value `search_kb` already returns per result. Fixed by telling it explicitly to copy the tool's `citation` field verbatim, never write its own. Re-verified live: A2, A5, M1 all cite correctly now.

Both fixes also happened to resolve A4: with `search_kb` reliably called (fix 1) and the grounding rule additionally telling the model to check whether retrieved text actually supports the claim (added while fixing #2), A4 now retrieves and cites `SPEC#9.0` correctly. Not a coincidence chased separately — a side effect of fixing the two clearer bugs first, confirmed by rerunning A4 after.

## What's still not fixed, and why

**Refusal doesn't verify via retrieval first (U1-U3).** All three still get refused correctly in outcome, but via the model's own general judgment ("this isn't a coding question") rather than by calling `search_kb`, checking the score, and emitting the specified `INSUFFICIENT_CONTEXT: <what is missing>` format. Safe today because these three are obviously off-topic — but this means the *mechanism* Day 4 asks for isn't actually what's producing the safe outcome, and a query that merely *sounds* in-domain but isn't covered by the corpus is untested. Not fixed here: the two changes made were targeted at the failures actually observed (wandering, citation format), not a speculative third prompt iteration for a gap that hasn't been shown to cause a wrong answer yet.

**A numeric grounding threshold τ is not reliable at this scale — measured, not assumed.** Queried the three genuinely unanswerable questions directly against `search_kb`: their top scores (0.0164–0.0323) fall squarely inside the same range as correct hits (0.026–0.033) *and* inside A4's wrong-but-confident hit (0.0318). The fused RRF score does not cleanly separate "actually relevant" from "coincidentally similar" at this corpus size. `GROUNDING`'s refusal rule is worded around the model judging whether retrieved *text* supports the question, not a score cutoff — because the score alone, checked directly, does not carry that signal here.

## Next, if this keeps being worked on

Named, not built: a held-out set of "sounds in-domain but isn't covered" queries to actually test the U1-U3 gap above, and revisiting `docs/research/rag.md`'s Contextual Retrieval entry if a wider smoke set ever reproduces the A4-style wrong-chunk-high-confidence failure again.
