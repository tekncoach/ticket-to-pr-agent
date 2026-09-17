# Shadow mode

Real input, live reads, every write a no-op that returns the payload it
intended. One pairwise record per unit of traffic, redacted before it touches
disk, and zero writes proved by the integration rather than by us.

```
make shadow-harvest REPO=encode/httpx   # traffic: real issue -> merged-PR pairs
make shadow-audit-before ISSUES=13,14,16 # count what a write would move
make shadow-run LIMIT=15                 # the batch, each unit at its base commit
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
settled. Two of the four finished units in the batch below are partials, and
both were called by hand with the reason written down — without that they
would have counted the same as the one exact hit.

**Guardrail — completion rate.** How many units reached a stated proposal at
all. High agreement over the four units that finished out of fifteen that did
not is a number that flatters itself, so the two travel together and neither is
reported alone.

## What the batch found

Fifteen units against `encode/httpx`, each at the parent commit of the pull
request that resolved it.

```
15 units, 4 reached a proposal
  file agreement   0.75  (exact 0.25)
  completion rate  0.267   <- the guardrail
  latency          median 32909ms, max 50255ms
  stopped on allowlist_workaround: 4, duplicate_tool_call: 4,
             max_turns: 2, repeated_tool_failure: 1
```

Agreement counts one exact hit (`#2666`, `httpx/_auth.py` — the missing
`file=None` default on `NetRCAuth`) and two partials adjudicated
`half-the-fix`: `#2715` put `socket_options` in
`httpx/_transports/default.py`, and `#2443` moved the `httpcore` constraint in
`pyproject.toml`. The fourth finished unit, `#1278`, implemented server-sent
events in `httpx/_models.py` when the merged pull request resolved the issue by
documenting an existing third-party package — it built the feature rather than
finding that someone else had (`F48`, recorded and not fixed: choosing between
building and pointing at prior art is a judgement this metric cannot see).

Both partials are written up in `adjudications.json` with the reason, because
"found half the fix" and "touched a file that happens to overlap" are the same
word until someone says which.

### The batch before this one was measuring the wrong thing

The first fifteen units ran against current `main` while the traffic is
historical — so the agent was asked for changes **already present in the file
it was reading**. It noticed before we did. On `#2715` it said outright that
`socket_options` *"IS already implemented … the actual functionality was
already in place"*, which was true, and the comparator scored it as half a hit
for touching the right file. `base_sha` had been in every traffic record since
the first harvest and was never used.

`checkout_base()` now puts the tree at the pull request's parent commit before
each unit. A unit that cannot get there carries `tree_error` and the comparator
gives it the `wrong-tree` verdict instead of a score — because on the wrong
tree, "it found the place" and "it found nothing to do" both mean something
else. That is `F45`, and it is ours.

### What n=15 says about the two modes n=3 guessed at

The three-unit batch was used to claim both open modes were structural. Fifteen
units on correct trees say otherwise, and the correction runs in both
directions:

- **`F44` was not seen once.** `run_tests` failing on a clone with no
  virtualenv looked like a mode at n=3 and is closer to an incident.
- **`F43` is real and small** — the agent improvising a shell to write, 2 units
  and 5 refusals.
- **`F46` is new and larger**: 4 units stopped reaching for ordinary plumbing
  the allowlist does not carry — `xargs`, `echo`, `python3`. That is a
  different mode from improvising a write path; these are read-side commands on
  a codebase the agent has to discover, and no three-unit batch could have
  shown it.
- **`F47` is the other new one**: 4 of the 11 units that did not finish hit no
  guard at all — two exhausted their turns, two repeated a call they had
  already made, with nothing refusing them.

So the guards are involved in 7 of 11 incompletions, which supports `F39`'s
umbrella claim and not the specific two modes named under it. The n=3
inference was wrong in the direction a reader would predict, and it is left
written down above rather than quietly replaced.

## Why the batch stops at fifteen

The full corpus is 60 units and the command is `make shadow-run LIMIT=60`.
Measured from these runs rather than estimated — 7k uncached input, ~175k
cache-read and 3.5k output tokens per unit — that is **about $0.045 a unit,
roughly $2.70 for all sixty**, and between thirty and seventy minutes of wall
clock.

Cost is not the reason. Fifteen was chosen to test a claim three units could
not support, and it did: it overturned `F44`, sized `F43`, and surfaced two
modes that were not visible at all. What sixty would buy now is a readable
agreement rate — at 4 finished units, 0.75 rests on three cases and should be
read as "the agent lands on the right file when it gets that far", not as a
rate. Completion at 0.267 is the number to move, and moving it is a code
change rather than a sample-size change.

**And the agent still has no parallel system to shadow.** Shadow mode's value
is running beside something already serving traffic; nothing here does that
job. `Baseline.unavailable()` exists for exactly this and says so rather than
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
