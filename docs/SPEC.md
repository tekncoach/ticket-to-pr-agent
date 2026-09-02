# Ticket → PR agent — SPEC

A coding agent that turns a GitHub Issue on `tekncoach/liberty-rider-myroadtrips` into a pull request that passes CI. Target loop: Cognition (Devin-style).

## Problem

`liberty-rider-myroadtrips` is a real Python app — sync, crypto, multitenant, a 17-file test suite and GitHub Actions CI. On a repo like this, turning a tracked issue into a merged change is entirely manual.

Today an engineer reads the issue, finds the relevant code, writes the diff, opens the PR, and babysits CI until it goes green. Every step is human, and none of it scales with the backlog: twice the tickets means twice the hours.

An agent fits here — and a form or a search box would not — because the task is multi-step and hard to fully specify up front. Crucially, it is also **objectively verifiable**: the test suite and CI are the oracle that says whether the work is actually correct, so the agent's output can be checked instead of trusted.

## Users & surfaces

- **Primary user / channel:** Software Engineer, who puts an issue in front of the agent; served over an API and answered back through a comment on the issue. The Product Manager is a secondary reader who follows status via that comment.
- **Auth model:** service account (a dedicated bot / GitHub App token). This is a single-repo automation, not a multi-user product — no per-user OAuth.

## Trigger (which issues, and how they reach the agent)

- **Which issues are agent-treatable:** exactly those carrying the label `agent:ready` with a usable body. That label is the contract — no label, no run. A Kanban column (GitHub Projects) would be a heavier variant of the same label idea; not used here.
- **POC trigger:** explicit and manual. The engineer hands the agent an issue number — `POST /v1/run {"issue": 42}` (or `make run-ticket ISSUE=42`). No public endpoint, no infra.
- **Production trigger:** a GitHub webhook on the `issues` / `labeled` event. When `agent:ready` is added, GitHub POSTs to our service and the run starts (push, real time). Polling the API for labelled issues is the fallback when no public URL is available.

## Happy path (step list)

1. The trigger delivers an issue number (manual POST for the POC; webhook on `agent:ready` in production).
2. `fetch_ticket(issue_id)` returns the issue title and body as the spec.
3. The agent works inside a checked-out working copy of the repo. It navigates the code live with `grep_repo` / `read_file` (and consults the prose knowledge base via RAG) to locate the relevant code.
4. The agent implements the change by **editing files** with `edit_file`. Code is written as iterative, targeted edits to the working tree — there is no one-shot "emit a diff" step.
5. The agent runs the test suite locally with `run_tests`; if red, it reads the failures, edits again, and repeats until the relevant suite is green (or gives up when the turn budget is spent — see Control points).
6. `open_pr(branch, description)` pushes the working-tree diff as a **draft** PR (shadow mode).
7. `get_ci_status(pr_id)` reads the GitHub Actions result.
8. `comment_on_ticket(issue_id, status)` posts the outcome back on the issue.

## Tools (OpenAPI-ish)

| Tool | Input | Side effects | Failure modes |
|------|-------|--------------|---------------|
| fetch_ticket | issue_id | none | issue missing, empty body |
| grep_repo | pattern | none | no matches |
| read_file | path | none | file not found |
| edit_file | path, old, new | **writes working tree** | string not found, ambiguous match |
| run_tests | selector? | none (in the run's sandbox) | failing tests, missing deps, timeout |
| open_pr | branch, description | **writes** (draft PR) | 409 branch exists, 422 validation |
| get_ci_status | pr_id | none | CI still running, timeout, no workflow |
| comment_on_ticket | issue_id, status | **writes** | 404, 429 rate-limit |

The agent codes by editing files in the working copy (`edit_file`), not by emitting a patch. There is no `write_code` / `generate_diff` tool — the diff `open_pr` submits is the cumulative `git diff` of the working tree. On an **ambiguous match**, `edit_file` refuses and asks the agent to re-issue the edit with more surrounding context — it never silently picks the first match. Git and GitHub operations are hand-written calls for now, to keep the mechanics low-level and explainable; a later brick replaces them with the `gh` / `gog` CLI.

## Code navigation & RAG

- **Code is navigated live, not vector-indexed.** The agent reads the repo on demand with `grep_repo` + `read_file` on the working checkout. On a single small repo this beats vector RAG: the reads are exact and current, follow imports, and never break on chunk boundaries the way code chunks do. A structural index (tree-sitter / ctags) or a codebase-graph service (Graphify-class platforms) is the productionization path if the repo grows — not needed at this size.
- **RAG is scoped to the prose knowledge base**, which is where semantic search actually earns its place (and the artifact the sprint asks for on Day 4): `README`, `CONTRIBUTING`, docs, and past resolved Issues / PRs. Chunking ~800 tokens / ~120 overlap with metadata (source path, kind: doc/issue/pr); hybrid BM25 + dense vector over pgvector; no re-ranker in v1. Grounding rule: refuse (ask for clarification instead of inventing) if no chunk scores above threshold τ = 0.35.

## Control points (local gates)

The CI is the oracle; the agent's job is to converge to green CI. The only local gate before `open_pr` is **running the tests**. Lint, type-check, and coverage stay CI-only for now — they are added as local gates later, and only if Day 9 failure-mode analysis shows they are top causes of first-attempt CI failures. We do not pre-add controls whose need we have not measured.

**Turn budget.** The edit→test loop is capped at `MAX_TURNS` (default 8) cycles. On exhaustion the agent stops, opens **no PR**, and posts a "could not resolve after N turns" comment via `comment_on_ticket`. It never ships a PR it could not get green — a failed run is a comment, not a broken draft left behind.

## Sandbox & isolation

Each ticket run executes in its **own ephemeral sandbox — one per run, never shared** (candidate: an exe.dev-style per-run sandbox). The split of responsibility:

- **The orchestrator** (the FastAPI service) owns the agent loop, the LLM calls, and the structured logging. The loop *drives* the sandbox; it does not run inside it.
- **The sandbox** is the execution surface: it holds a per-run git worktree / clone and runs `edit_file`, `run_tests`, the linter, and git.

Keeping the loop in the orchestrator keeps the LLM key and all control / observability central, and makes concurrency safe by construction: two tickets are two sandboxes with two worktrees, so they cannot collide or corrupt a shared checkout. `open_pr` pushes from that per-run worktree, and the sandbox is torn down on completion or give-up. This is the v1 shape; it is revisited only if measurement demands it.

## SLOs

- **p95 latency:** ≤ 300 s per ticket→PR run (local test execution dominates).
- **cost/request:** ≤ $0.20 per run on the default model (`claude-haiku-4-5`); re-baseline when the model is raised.
- **grounded rate:** ≥ 95% (the edits touch only files/symbols that exist in the repo the agent actually read).
- **tool success rate:** ≥ 98% (tool calls that execute without error).
- **★ north-star:** ≥ 40% of generated PRs pass GitHub CI on the first attempt. This is the honest quality measure — the residual gap after the local `run_tests` gate is env divergence (local ≠ CI) plus CI-only gates (lint, type-check, coverage, integration). Days 7–9 push this number up.

## Shadow / rollout

- **Shadow mode replays history.** Instead of a percentage of live traffic (which does not map to an agent whose every output a human reviews), shadow runs the agent on issues that were **already resolved** and diffs the agent's PR against the human PR that actually merged. Zero production risk, and it is the baseline for the eval (Day 11 — diff against baseline and quantify value). Metrics: first-attempt CI pass, and how close the agent's change is to the human's.
- **Progressivity is autonomy per issue-class, not a traffic percentage.** As measured trust grows: (1) draft PR, human reviews everything, the agent never merges → (2) the agent marks the PR ready-for-review once CI is green → (3) auto-merge on green for a narrow, well-defined class (dependency bumps, small scoped tickets) → (4) widen the trusted classes. Kill switch: a label / env flag that instantly reverts everything to shadow (or off).

## Out of scope

The agent never touches these paths, and the boundary is **enforced, not merely requested**: a path denylist checked inside `edit_file` rejects edits to them at the tool boundary (implemented when `edit_file` lands, Day 3). A prompt instruction alone would be a suggestion, not a boundary.

1. Auth and crypto changes.
2. Multi-tenant isolation logic.
3. Database migrations.
