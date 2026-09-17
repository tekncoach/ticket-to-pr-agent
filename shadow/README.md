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

Three units. All three refused, for the same reason, and none attempted a
write:

> *"The system is configured to work with the liberty-rider-myroadtrips
> repository. I cannot work on issues from external repositories."*

That is correct behaviour, and it is the finding. **This agent is
single-target by construction** — one `TARGET_REPO`, one checked-out
workspace, one token, a limitation `README.md` already names — so traffic from
a foreign repository measures the boundary, not the work. The pairwise records
are legible and true, and what they say is *"refused, correctly, every time"*.

Running fifty more of them would produce fifty more refusals.

## Why the batch stops at three

Three reasons, in the order they actually decide it.

**The comparison has nothing to compare.** A baseline is a real fix; the
proposal is a refusal. The pair is honest and it is the same pair sixty times.

**The agent has no parallel system to shadow.** Shadow mode's value is running
beside something already serving traffic, and there is nothing here doing that
job. `Baseline.unavailable()` exists for exactly this and says so rather than
inventing one.

**And the cost is real but last.** It is the weakest of the three, and putting
it first would be the wrong argument.

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
