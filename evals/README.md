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
make eval        # needs .env: LLM_API_KEY, HF_TOKEN, and a built corpus
```

They **skip** what they cannot reach rather than failing — an absent corpus or
key is a missing prerequisite, not a regression. `-rs` prints what was skipped
and why, so a run that quietly measured nothing cannot look like a pass.

CI does not run them. It has no secrets, on purpose, and a job that charges the
Anthropic account on every push is a job someone eventually disables.

## What is here today

`test_rag_smoke_set.py` — 10 queries against the real corpus (5 answerable, 3
unanswerable, 2 multi-hop), with hit@6 and citation accuracy recorded in
[`docs/RAG-SMOKE-SET.md`](../docs/RAG-SMOKE-SET.md). It is the only real eval
this project has so far, and it is the seed the golden set grows from: it
already has the shape — an input, an expectation, and a refusal case that is
supposed to refuse.
