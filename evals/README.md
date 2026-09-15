# Evals — the agent's behaviour, not our code's

`tests/` asks *does this code do what we wrote?* This directory asks *does the
agent behave correctly?* They are different questions and they must not share a
command, because they disagree about what failure means.

| | `tests/` | `evals/` |
|---|---|---|
| Deterministic | yes | no — same input, different output |
| Model | mocked | real, and it is the subject |
| Cost | free | real money per run |
| Runtime | seconds | minutes |
| Failure | red means broken | a score, compared to a threshold |
| Runs | every commit, CI gate | before a release, after a prompt or model change |
| Reports | pass / fail | pass@1, tool precision/recall, faithfulness, $/run |

A threshold like *pass ≥ 0.80* is meaningless against unit tests, where the
only acceptable number is 1.0. That is the whole reason for the split.

## Two kinds of eval live here

**Deterministic.** Did it call the right tool? With arguments valid against the
schema? Did it cite? Did it refuse when the corpus could not answer? These have
ground truth and need no judge — `==` is enough.

**Judged.** Is the answer faithful to what retrieval actually returned? There is
no correct string to compare against, so a model scores it 1–5 with a rationale
that a human can disagree with.

## Running them

```
make golden                      # the whole set: retrieval free, model cases in ~2 min
make golden TIER=retrieval       # no model at all
make golden SPLIT=adversarial
make golden ID=ref-001 ID=tool-011
make golden-check                # has the frozen set drifted?
make eval                        # the older pytest-based evals
```

They **skip** what they cannot reach rather than failing — an absent corpus or
key is a missing prerequisite, not a regression. `-rs` prints what was skipped
and why, so a run that quietly measured nothing cannot look like a pass.

CI does not run them. It has no secrets, on purpose, and a job that charges the
Anthropic account on every push is a job someone eventually disables.

## What is here

[`golden.jsonl`](golden.jsonl) — 52 labelled cases, frozen as v1 by
[`golden.lock.json`](golden.lock.json). 70% regression core, 20% hard, 10%
adversarial. Forty-two carry an origin that is an observed run or a recorded
scenario rather than an invention, and eleven reproduce failures this system
currently gets wrong, which is the only way the set measures anything.

[`schema.py`](schema.py) — the shape, and the closed vocabularies. Fourteen
forbidden behaviours, three tiers, three splits, seven tool names, all
`Literal`. A line that misspells one fails to load rather than scoring as a
behaviour nobody implemented.

[`scorers.py`](scorers.py) — five deterministic scorers over the trace the
runtime already writes. Eleven of the fourteen behaviours have a detector;
three cannot be settled by any arrangement of events and are reported
**unchecked** rather than absent.

[`runner.py`](runner.py) — one rule: read-only tools run for real, anything
that writes or costs answers from the case. That is why the write cases are
runnable at all — no case at this tier *can* write.

[`judge.py`](judge.py) + [`JUDGE-CALIBRATION.md`](JUDGE-CALIBRATION.md) — the
faithfulness judge and the measurement that decides whether to believe it.
κ 0.651–0.823 over five passes against human labels, and still delegated nothing — its residual errors all lean toward passing invented content.

[`failure-modes.csv`](failure-modes.csv) + [`FAILURE-MODES.md`](FAILURE-MODES.md)
— the triage of the first full pass, one row per case, checked against the runs
it names so it cannot drift from them.

[`test_rag_smoke_set.py`](test_rag_smoke_set.py) — 10 queries against the real
corpus, with hit@6 and citation accuracy in
[`docs/RAG-SMOKE-SET.md`](../docs/RAG-SMOKE-SET.md). It was the seed the golden
set grew from, and its ten queries are now cases in it.

## The three tiers, and why they exist

A suite nobody can afford to run is not a gate, so every case declares what it
costs to run.

| Tier | What runs | Cost |
|---|---|---|
| `retrieval` | `search_kb` only, no model | free, deterministic |
| `single_turn` | the real model deciding, against staged tools | cents |
| `agent_run` | the whole loop on a disposable checkout | dollars and minutes |

Only the first two run from `make golden`. The six `agent_run` cases are
started on demand, before a prompt or model change — never in a gate.

**The scorer is reproducible; the model is not.** `temperature=0` does not make
an LLM deterministic, and one case has already scored 0.00 and 1.00 on the same
input. Single-pass numbers here are point estimates — which is why every
threshold reads the lower bound of a range, and why `PASSES=3` makes the gate
**stricter**, not noisier.

## The gate, and where it runs

`evals/gates.yaml` holds the thresholds; `make golden` compares against them and
exits non-zero on a breach. `make golden NO_GATE=1` measures without blocking.

Two rules decide every line of it. A threshold reads the **lower bound**, never
the median. And a threshold with nothing to compare against is **skipped and
says so** — a gate reporting green for checks it never ran is worse than no
gate, because someone believes it.

Two of them ship disabled, each with its reason in the file: faithfulness,
because gating on a judge at κ 0.651–0.823 with six cases that flip on
identical input is a barrier that opens at random; and cost, because nothing
here hardcodes a vendor price list that goes stale in silence.

**The gate does not run in CI, and the reason is data, not money.** A stateless
runner has neither `data/kb/` — the corpus cites sources that are not ours to
redistribute — nor the target checkout, which is built into the image rather
than the repository. Without those, `search_kb` and `bash` have nothing to read,
so a CI eval job would skip every case and report green for a suite it never
ran. So the split is:

| | where | what |
|---|---|---|
| CI, every push | GitHub | `make test` and `make golden-check` — hermetic, free, no secrets |
| `make hooks` | your machine | `scripts/pre-push` adds the retrieval gate, which has the corpus |
| on demand | anywhere with `.env` | `make golden TIER=single_turn PASSES=3` |

The way to move the eval gate into CI is to stop needing the data: each run
already writes its full trace, so scoring a *recorded* run costs nothing and
needs no secrets. A replay gate over committed traces is the next thing that
would make this cheap enough to be automatic. Not built.
