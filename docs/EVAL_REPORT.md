# docs/EVAL_REPORT.md

## Setup
- Model / temp: ___
- Golden set: N=__, hash=___
- Corpus hash: ___
- Agent commit: ___

## Metrics (latest vs baseline)
| Metric | Baseline | Latest | Δ |
|--------|----------|--------|---|
| pass_rate | | | |
| p0_pass | | | |
| mean_faithfulness | | | |
| tool_precision | | | |
| grounded_rate | | | |
| p95_latency_ms | | | |

## Failure modes (count / examples)
| Mode | Count | Example case id | Mitigation |
|------|-------|-----------------|------------|
| retrieval_miss | | | raise k / hybrid |
| hallucination | | | raise τ / force refuse |
| wrong_tool | | | tighten descriptions |

## Drift alerts
Rules: fail if pass_rate drops >3pts or new P0 appears.

## What I would do next (interview answer)
1. ...
2. ...
