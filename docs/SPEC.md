# Ticket → PR agent — SPEC

A coding agent that turns a GitHub Issue on `tekncoach/liberty-rider-myroadtrips`
into a pull request that passes CI. Target loop: Cognition (Devin-style).

## Problem
On `liberty-rider-myroadtrips` (a real Python app: sync / crypto / multitenant,
17-file test suite + GitHub Actions CI), turning a tracked issue into a merged
change is manual: an engineer reads the issue, finds the relevant code, writes
the diff, opens the PR, and babysits CI. That is slow and it does not scale with
backlog. An agent fits — not a form or a search box — because the task is
multi-step, hard to fully specify up front, and **objectively verifiable**: the
test suite and CI are the oracle that says whether the work is correct.

## Users & surfaces
- **Primary user / channel:** Software Engineer, who triggers the agent by
  tagging a GitHub Issue; served over an API (`POST /v1/chat`) and back through
  a comment on the issue. Product Manager is a secondary reader who follows
  status via the issue comment.
- **Auth model:** service account (a dedicated bot / GitHub App token). It is a
  single-repo automation, not a multi-user product — no per-user OAuth.

## Happy path (step list)
1. An issue is tagged → `fetch_ticket(issue_id)` returns the spec.
2. Agent retrieves the relevant code context (RAG over the liberty-rider corpus).
3. Agent generates the diff **in-loop** (no separate `write_code` tool — code
   generation happens in-context, not via a named tool).
4. Agent runs the test suite locally → `run_tests(...)`; if red, it iterates on
   the diff and repeats. It only proceeds when the relevant suite is green.
5. `open_pr(branch, diff, description)` opens the PR **as a draft** (shadow mode).
6. `get_ci_status(pr_id)` reads the GitHub Actions result.
7. `comment_on_ticket(issue_id, status)` posts the outcome back on the issue.

## Tools (OpenAPI-ish)
| Tool | Input | Side effects | Failure modes |
|------|-------|--------------|---------------|
| fetch_ticket | issue_id | none | issue missing, empty body |
| run_tests | paths?/selector? | none (local sandbox) | failing tests, missing deps, timeout |
| open_pr | branch, diff, description | **writes** (draft PR) | 409 branch exists, invalid diff, 422 validation |
| get_ci_status | pr_id | none | CI still running, timeout, no workflow |
| comment_on_ticket | issue_id, status | **writes** | 404, 429 rate-limit |

## RAG
- **Corpus:** the liberty-rider codebase (`app.py`, `sync.py`, `liberty_client.py`,
  `db.py`, migrations, tests), the repo's GitHub Issues as ticket specs, and
  `README` / `CONTRIBUTING` / docs as the knowledge base. `.py`, `.sql`, `.md`;
  small (single repo); refreshed on each ingest run (Day 4).
- **Chunking:** ~800 tokens / ~120 overlap, symbol-aware where possible, with
  metadata (source path, symbol name, kind: code/test/doc).
- **Retrieval:** hybrid BM25 + dense vector (pgvector); no re-ranker in v1.
- **Grounding rule:** refuse (ask for clarification instead of inventing) if no
  chunk scores above threshold τ = 0.35.

## SLOs
- **p95 latency:** ≤ 300 s per ticket→PR run (local test execution dominates).
- **cost/request:** ≤ $0.20 per run on the default model (`claude-haiku-4-5`);
  re-baseline when the model is raised.
- **grounded rate:** ≥ 95% (the diff touches only files/symbols that exist in
  the retrieved context).
- **tool success rate:** ≥ 98% (tool calls that execute without error).
- **★ north-star:** ≥ 40% of generated PRs pass GitHub CI on the first attempt.
  This is the honest quality measure — the residual gap after the local
  `run_tests` gate is env divergence (local ≠ CI) plus CI-only gates (lint,
  type-check, coverage, integration). Days 7–9 push this number up.

## Shadow / rollout
- **Shadow mode is the default** (`SHADOW_MODE=true`): the agent opens the PR as
  a draft and never marks it ready, so its output is compared against the human
  baseline without acting for real. Staged percentages (5% → 25% → 100%) and the
  kill switch are designed on Days 10–12; not built yet.

## Out of scope
1. Auth and crypto changes (the agent never edits the auth or encryption paths).
2. Multi-tenant isolation logic.
3. Database migrations.
