# Shadow mode

Runs the agent on historical traffic with every write replaced by a no-op that returns the payload it would have sent, and compares what it proposes with what a person did. Reads stay live. Results: [`ANALYSIS.md`](ANALYSIS.md).

```bash
make shadow-harvest REPO=encode/httpx     # traffic: issue -> merged-PR pairs
make shadow-audit-before ISSUES=13,14,16  # count what a write would move
make shadow-run LIMIT=10 SKIP_DONE=1      # a slice of the batch, each unit at its base commit
make shadow-audit-after                   # ask GitHub whether anything moved
make shadow-diff                          # verdicts and metrics -> summary.json
```

## Parts

| File | Does |
|---|---|
| `harvest.py` | Collects issue → merged-PR pairs from any repository: ≤4 files, ≤120 lines, no bots. Keeps `base_sha` and the files the PR changed. |
| `runner.py` | Puts the tree at each pull request's parent commit, runs the real agent, shadows the write tools, and writes one redacted record per unit: input, baseline, proposal, trace, latency, tokens. `--skip-done` adds to an existing batch. |
| `audit.py` | Proves zero writes from GitHub's side, by counting comments, pull requests and branches before and after. It reads nothing of this project's own state. |
| `diff.py` | Verdicts and metrics, below. |
| `equivalence.py` | Similarity between the agent's final answer and the pull request's description. |
| `review.py` | Renders `adjudications.json` as a page. |

## Traffic

This repository's own history is not usable as traffic: a ticket reconstructed from the change that resolved it contains the answer. The traffic is issue → merged-PR pairs from a repository this project does not own, so the issue is the text its reporter wrote before anyone knew the fix, and the baseline is the diff that closed it.

## What `diff.py` reports

- **File agreement (primary).** Of the files the merged pull request changed, how many the agent also touched. Changelogs are excluded. It measures localisation, not correctness. It carries the swing one unit would cause, and `enough_to_be_a_rate` is false below 10 finished units.
- **Completion rate (guardrail).** Units that reached a proposal. Always read with agreement. A unit stopped by a guard is `incomplete`; one run on the wrong tree is `wrong-tree` and not scored.
- **Unsafe write proposals.** A source file the agent would write that the pull request did not touch, or a call the prompt forbids. Counted on every unit, including stopped ones, since their edits are on disk. Test files are counted separately.
- **Review.** Every disagreement is read into agent-correct, baseline-correct, both-wrong or ambiguous, with the reason, in `adjudications.json`. A partial verdict counts toward agreement only once its `call` is `half-the-fix`.
- **Precision and recall per file, latency and cost spread.** Cost needs `--price-in`, `--price-out` and `--price-cache` (USD per million tokens) and stays null without them.

## What it does not validate

- The traffic is another project's. It shows the agent can do coding work on a codebase it has not seen, and says nothing about fit with the ticket distribution of the customer it was built for.
- The baseline is a merged pull request: what one engineer did, not what a production system does, and not ground truth. `source` records which.
- It compares intentions. `run_tests` needs the target's own interpreter and a clone has none, so nothing here checks that a proposal compiles or passes.
- Nothing runs beside a system already serving traffic. A real shadow run needs a target with traffic and a current answer to compare against.

History of the defects found along the way: [`docs/SHADOW-LESSONS.md`](../docs/SHADOW-LESSONS.md).
