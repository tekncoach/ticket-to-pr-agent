# Cost and limits

## Cost

Measured from the traces in `tmp/sessions/`, on `claude-haiku-4-5`, at the time of writing. Re-measure before quoting.

| | |
|---|---|
| A knowledge-base question | **$0.011–$0.047** per run, 1–4 `search_kb` calls |
| Context window used | **3% of 200k** at the end of a typical run (occupancy, not accumulated token spend) |
| Target suite inside the container | 175 tests, **12.6s** |
| Retry cost, worst case | 9 HTTP requests for one comment (`MAX_CYCLES × (READ_ATTEMPTS + 1)`) |
| Golden set, first full pass | **31 of 44** scored cases via `make golden`: 16 retrieval cases free, 28 model cases in ~135s |
| Judge agreement with human labels | quadratic κ **0.651–0.823** over five passes, median 0.670 |

## Known limits

- **One completed ticket, not a track record.** The loop has run end to end once, on one narrow ticket, and took eight attempts ([`FIRST-COMPLETED-RUN.md`](FIRST-COMPLETED-RUN.md)). A first-attempt CI-pass rate needs a run of tickets behind it.
- **Six of those eight blockers were this project's own guards**, not the model: `sed` refused outright, globs unexpanded, `git log` denied, a fruitless `grep` reported as a tool failure, and an auth-symbol denylist that listed `get_session_user`, the dependency every protected endpoint declares, so writing any protected endpoint was blocked. A guard has to name what must not be **altered**, not what may not be **called**; one that blocks correct work gets switched off rather than fixed. Each is now a fix with a regression test; the arc is in commit `129ab0c`.
- **Read-then-write is not atomic.** Two concurrent runs could both pass the duplicate check before either writes. Safe today only because runs are serialised. The assumption and its blast radius are in [`resilience.md`](resilience.md); there is no lock.
- **Nothing resumes.** A run that stops re-derives work already done.
- **The corpus is not in the repository.** It cites sources that are not ours to redistribute, so `data/kb/` is mounted, not baked. Without it `search_kb` fails, typed as `unavailable`, and the agent says so.
- **The faithfulness judge is not delegated the three behaviours it was built for** (`invent_figure`, `fabricate_tool_result`, `follow_injected_instruction`). It agrees with human labels at κ 0.688, but its remaining errors lean one way: a point too generous on fabricated content, on every pass. Those three stay reported as unchecked. It once named a fabricated citation and still scored the answer 4 on all ten passes, so that rule is now enforced by a clamp rather than asked for in the prompt; probe detection went from 3 of 4 to 4 of 4.
- **The judge is not deterministic, and six cases will not settle.** Sampled five times on the same labels, it scored one answer 5, 2, 5, 5, 5. The worst is a write case whose only evidence is `{"recorded": true}`: a stub receipt leaves nothing to decide against. Fixing the receipts is a prerequisite to trusting the judge on writes.
- **Three golden cases cannot run**, because their fixtures do not exist: a poisoned corpus chunk, an injected source comment, and an already-open pull request. They are counted as unrunnable, never as passing.
- **`get_ci_status` does not exist**, so the loop ends at a draft PR and never learns whether CI went green.
- **One tenant, one repo, one token.** See [`DESIGN.md`](DESIGN.md#tenancy).
