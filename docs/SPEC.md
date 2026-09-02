# docs/SPEC.md

## Problem
One paragraph: who hurts, current workaround, why an agent (not a form/search box).

## Users & surfaces
- Primary user / channel (Slack, API, internal UI)
- Auth model (service account, per-user OAuth)

## Happy path (step list)
1. User asks X
2. Agent retrieves Y
3. Agent calls tool Z
4. Returns grounded answer + citations / action receipt

## Tools (OpenAPI-ish)
| Tool | Input | Side effects | Failure modes |
|------|-------|--------------|---------------|
| search_kb | query, k | none | empty, stale |
| create_ticket | title, body, priority | writes | 429, validation |

## RAG
- Corpus: ___ (file types, size, refresh cadence)
- Chunking: size/overlap + metadata (source, section, date)
- Retrieval: hybrid BM25+vector or dense-only; re-rank: yes/no
- Grounding rule: refuse if no chunk above threshold τ

## SLOs
- p95 latency: ___ ms
- cost/request: $___
- grounded rate: ≥ ___%
- tool success rate: ≥ ___%

## Shadow / rollout
- Shadow compares agent suggestion vs baseline human/system action
- Stages: shadow → 5% → 25% → 100% with kill switch

## Out of scope
List 3 things you will not build.
