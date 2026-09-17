# Shadow mode

Real input, live reads, every write a no-op that returns the payload it
intended. One pairwise record per unit of traffic, redacted before it touches
disk, and zero writes proved by the integration rather than by us.

```
make shadow-harvest REPO=encode/httpx   # traffic: real issue -> merged-PR pairs
make shadow-audit-before ISSUES=13,14,16 # count what a write would move
make shadow-run LIMIT=3                  # the batch
make shadow-audit-after                  # ask GitHub whether anything moved
```

## Where the traffic comes from, and why not from here

The obvious source was this repository's own history: 96 commits, each a piece
of work with its answer attached. It is useless as traffic, and the reason
generalises — **a ticket reconstructed from the change that resolved it
contains the answer.** *"Show the share URL as text, not only inside an input"*
is not a request, it is a summary of the fix. Replaying that measures how well
the ticket was paraphrased.

So the traffic is **issue → merged-PR pairs from a repository we do not own**:
60 of them from `encode/httpx`, filtered to work an agent could plausibly do
(≤4 files, ≤120 lines, no bots). The issue is the text its reporter wrote
before anyone knew the answer. The baseline is the diff that closed it, written
by people who had never heard of this agent.

Nothing in `harvest.py` is specific to any repository — `--repo` takes any of
them. A shadow runner coupled to its own project cannot answer the question a
shadow run exists to ask.

## What the sample batch found

Three units against a real checkout of `encode/httpx`, with `TARGET_REPO` and
`TARGET_WORKSPACE` pointed at the repository the traffic came from.

| unit | baseline | agent touched | stopped on |
|---|---|---|---|
| #3349 | *Docs minor fix* — 1 file | `httpx/_client.py` | `duplicate_tool_call` |
| #3111 | *Use more permissible types in ASGIApp* — 2 files | `httpx/_transports/asgi.py` | `repeated_tool_failure` |
| #2810 | *ASGI raw_path should not include the query* — 3 files | — | `allowlist_workaround` |

**Two of three located the same file the merged pull request changed**, in a
codebase neither the agent nor its corpus has ever seen. That is the encouraging
half.

**All three died on this project's own guards**, not on the work: an identical
bash call repeated, a rejected shell operator, and the cross-tool guard cutting
`cd` followed by `cat`. None of them reached a stated proposal.

That is the finding, and it is the same one the first completed ticket produced
— six of its eight blockers were our guards rather than the model. A shadow run
against unfamiliar traffic surfaces it again, immediately, and at a scale where
it is obviously systematic rather than anecdotal. The guards are individually
defensible; together, in a repository whose layout the agent has to discover,
they are the binding constraint.

## Why the batch stops at three

**It already answered the question.** Three units produced a consistent,
specific finding. Fifty more would produce it fifty more times, which is
spending to restate something rather than to learn it.

**And the agent has no parallel system to shadow.** Shadow mode's value is
running beside something already serving traffic; nothing here does that job.
`Baseline.unavailable()` exists for exactly this and says so rather than
inventing one.

Cost is real and comes last, because putting it first would be the weaker
argument.

## What the run cannot say

`run_tests` needs the target's own interpreter and a clone has none, so nothing
here verifies a proposal compiles or passes. Shadow compares intentions, and
these are intentions. Reading the file list as evidence of a working fix would
be the claim this whole page is built to avoid.

## What was built rather than argued

The runner works, on any repository, and the mechanism is complete:

- **Reads stay live.** Only the consequence is removed. Simulating the reads
  too would mean measuring fixtures.
- **Redaction at write time**, on values rather than on the serialised
  document — the first version redacted the JSON itself and the phone pattern
  ate the punctuation between fields, producing records that would not parse.
- **Writes are refused by the runtime's own gate**, not by a switch this code
  invents for the occasion.
- **Zero writes is proved by GitHub**, in `audit.py`, by counting comments,
  branches and pull requests before and after. `SHADOW_MODE`, the write gate
  and the receipts are all ours, and a bug in any of them produces exactly the
  same reassuring output as a correct run. The audit asks the system we did not
  write.

## What would make this real

A target with traffic and a system already handling it — a support queue, a
triage path, anything with a current answer to compare against. On a
single-tenant repository with three open issues there is nothing to run beside.
That is a property of this project, not of the mechanism, and the mechanism is
here and portable for the next one.
