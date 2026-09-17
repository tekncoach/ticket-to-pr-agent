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

## What this run does and does not validate

The traffic is `encode/httpx`, not the agent's own target. That substitution
buys real issues written before anyone knew the answer, and it costs something
that has to be said rather than implied:

**this validates that the agent can do coding work on an unfamiliar codebase.
It says nothing about whether the agent fits this customer's ticket
distribution.** A shadow run's usual purpose is the second, and it needs a
target with traffic of its own.

The baseline carries the same caveat. A merged pull request is what an
engineer did, not what a production system currently does — `source` records
which, because reading a number without knowing that is how a comparison
flatters itself.

## The verdict, and how it is computed

`make shadow-diff` reads the pairwise log and answers the question the log
alone cannot.

**Primary metric — file agreement.** Of the files the merged pull request
changed, how many did the agent also touch. Deliberately narrow and narrow in a
checkable direction: finding the right place is necessary for a correct change
and nowhere near sufficient, so this is a floor on competence, never a claim of
correctness. Changelog entries are excluded — every pull request has one and it
says nothing about where the work is. Comparing the edits themselves needs a
judge, and this project does not hand its judge anything it can decide
deterministically.

**Partial verdicts are not counted until someone calls them.** A unit that
touched some of the baseline's files and not all of them is two very different
findings wearing one word — it found half the fix, or it touched a file that
happens to overlap — and nothing deterministic separates them. `shadow/diff.py`
writes each one to `adjudications.json` with what it hit and what it missed and
a blank call; until the call is `half-the-fix` it does not count as agreement,
and the summary prints how many are waiting so the number is never read as
settled. At n=3 this changes nothing. At n=60 it is the difference between a
metric and a flattering one.

**Guardrail — completion rate.** How many units reached a stated proposal at
all. High agreement over the three units that finished out of sixty that did
not is a number that flatters itself, so the two travel together and neither is
reported alone.

## What the sample batch found

Three units against a real checkout of `encode/httpx`, with `TARGET_REPO` and
`TARGET_WORKSPACE` pointed at the repository the traffic came from.

```
3 units, 1 reached a proposal
  file agreement   0.0  (exact 0.0)
  completion rate  0.333   <- the guardrail
  latency          median 28908ms, max 68934ms
  stopped on duplicate_tool_call: 1, max_turns: 1
```

| unit | baseline | agent touched | verdict |
|---|---|---|---|
| #3349 | `docs/advanced/transports.md` | `httpx/_client.py` | disagreed |
| #3111 | `httpx/_transports/asgi.py` | `httpx/_transports/asgi.py` | incomplete — `max_turns` |
| #2810 | `httpx/_transports/asgi.py`, `tests/test_asgi.py` | — | incomplete — `duplicate_tool_call` |

**The first batch completed nothing, and a third of that was our own prompt.**
It said *"you are inside a checkout of that repository"* without naming the
path, so the agent guessed `/repo/httpx/...` and the workspace guard refused it
— in all three units, before anything else went wrong. `agent/tickets.py`'s
`task_prompt` has named the workspace since day 4; this prompt was written
separately and did not. Naming it, with no other change, moved completion from
0.0 to 0.333 on the same three units. That is `F42`, and it is ours.

The other two stop reasons are the agent's, and both stay open. With no write
path in bash it improvises scripting to make an edit — heredocs, `python -c` —
and retries the same shape rather than reaching for the editor tool (`F43`).
And `run_tests` cannot work on a clone with no virtualenv, so it tries pytest
directly (`F44`); on foreign traffic there is no green suite to converge to at
all, which is a scope limit of this agent's loop, not a bug in it.

**Agreement is still 0.0, and the unit that finished is the reason.** `#3349`
went to `httpx/_client.py` for a fix that lived in `docs/advanced/transports.md`.
The one unit that had the right file — `#3111`, on `httpx/_transports/asgi.py` —
ran out of turns before stating a proposal, so it counts as incomplete and not
as a hit. Reading it as "one of three found the right place" would be counting
a run that never finished; the guardrail exists to stop exactly that.

That correction is the argument for building the comparator. Read by eye, the
first batch looked like two hits out of three, and it was written up that way.
The comparator says one, and it is right — which is exactly the gap between "I
have logs" and "here is what the run told me".

## Why the batch stops at three

The full corpus is 60 units and the command is `make shadow-run LIMIT=60`.
Running it costs, measured from this batch's own usage rather than estimated:
6.5k uncached input, 199k cache-read and 3.6k output tokens per unit, which on
`claude-haiku-4-5` is **about $0.045 a unit, roughly $2.70 for all sixty**, and
between thirty and seventy minutes of wall clock at the latencies above.

So cost is not the reason, and claiming it was would be the dishonest version
of this paragraph.

**The honest version is that three units do not yet support the claim they were
used to make.** An earlier draft of this section said both open modes are
structural and reproduce on every unit. They were each seen once. One
shell-improvisation stop and one test-oracle stop is a reason to expect a
pattern, not evidence of one, and a third mode that neither `F43` nor `F44`
predicts would not have had room to show up. `make shadow-run LIMIT=15` is the
slice that tests it — large enough to tell a dominant mode from a coincidence,
about $0.70, and it is the next thing this page should be updated with.

What sixty units still would not buy is a readable agreement number. Agreement
is only meaningful once completion is high enough to have a denominator; at
0.333 it is not, and raising completion is a code change rather than a
sample-size change.

**And the agent has no parallel system to shadow.** Shadow mode's value is
running beside something already serving traffic; nothing here does that job.
`Baseline.unavailable()` exists for exactly this and says so rather than
inventing one.

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
- **Writes are no-ops that return the payload they intended**, not refusals.
  The first version closed the runtime's write gate, and a gate answers
  DENIED — so the agent tried to edit, was refused, retried and stopped
  without ever stating what it would have changed (`F40`). A gate says no;
  shadow says done.
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
