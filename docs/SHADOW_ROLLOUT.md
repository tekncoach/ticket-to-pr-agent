# docs/SHADOW_ROLLOUT.md

## Executive summary
One paragraph: what we shadowed, agreement rate, go/no-go, next stage.

## System under test
Architecture, tools, RAG corpus, model. Link to demo + eval report.

## Shadow results
Embed key tables from ANALYSIS.md. Link to redacted sample logs.

## Staged rollout
| Stage | Traffic | Entry criteria | Exit criteria | Rollback |
|-------|---------|----------------|---------------|----------|
| 0 Shadow | 0% writes | eval gates green | N≥50, unsafe writes=0 | n/a |
| 1 Dogfood | internal | shadow OK | 1 week, CSAT≥__ | disable flag |
| 2 Canary 5% | 5% | dogfood OK | error_rate < baseline+1% | auto |
| 3 25% | 25% | canary OK | ... | auto |
| 4 100% | 100% | ... | ... | auto |

## Kill switches
- `AGENT_ENABLED=false`
- `ALLOW_WRITES=false`
- `MODEL_FALLBACK=baseline`
- Page on-call if unauthorized_write_proxy > 0

## Monitoring & ownership
- Metrics: ...
- Owner: DRI name/role
- Review cadence: weekly eval + shadow sample

## Risks & mitigations
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| hallucinated policy | M | H | refuse under τ + eval gate |
| runaway cost | L | M | max $ / day budget |

## Ask for stakeholders
Approve move to Stage 1 dogfood on DATE.
