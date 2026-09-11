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
3. The agent works inside a checked-out working copy of the repo. It navigates the code live with the `bash` tool (read-only allowlist: `grep`/`cat`/`find`/`ls`/`head`/`tail`/`wc`/`pwd`) — and consults the prose knowledge base via RAG — to locate the relevant code.
4. The agent implements the change by **editing files** with `edit_file`. Code is written as iterative, targeted edits to the working tree — there is no one-shot "emit a diff" step.
5. The agent runs the test suite locally with `run_tests`; if red, it reads the failures, edits again, and repeats until the relevant suite is green (or gives up when the turn budget is spent — see Control points).
6. `open_pr(branch, description)` pushes the working-tree diff as a **draft** PR (shadow mode).
7. `get_ci_status(pr_id)` reads the GitHub Actions result.
8. `comment_on_ticket(issue_id, status)` posts the outcome back on the issue.

## Tools (OpenAPI-ish)

| Tool | Input | Side effects | Failure modes |
|------|-------|--------------|---------------|
| fetch_ticket | issue_id | none | issue missing, empty body |
| bash *(Anthropic-defined `bash_20250124`)* | command (read-only allowlist) | none | shell operator rejected, executable not allowed, argument escapes workspace, timeout, non-zero exit |
| edit_file *(Anthropic-defined `text_editor_20250728`)* | command (view/create/str_replace/insert) + path | **writes working tree** | path escapes workspace, path denied, string not found, ambiguous match |
| run_tests | selector? | none (in the run's container) | failing tests, missing deps, timeout |
| open_pr | branch, description | **writes** (draft PR) | 409 branch exists, 422 validation |
| get_ci_status | pr_id | none | CI still running, timeout, no workflow |
| comment_on_ticket | issue_id, status | **writes** | 404, 429 rate-limit |

The agent codes by editing files in the working copy (`edit_file`), not by emitting a patch. There is no `write_code` / `generate_diff` tool — the diff `open_pr` submits is the cumulative `git diff` of the working tree. On an **ambiguous match**, `edit_file` refuses and asks the agent to re-issue the edit with more surrounding context — it never silently picks the first match.

Code navigation uses Anthropic's own `bash_20250124` client-side tool instead of a hand-rolled `grep_repo`/`read_file` pair — schema-less on the wire (Claude already knows the input shape), but Anthropic never executes it: our handler still does all the work, exactly like a hand-rolled tool would. Restricted to a read-only allowlist (`grep`, `cat`, `find`, `ls`, `head`, `tail`, `wc`, `pwd`); shell operators (`&&`, `|`, `;`, backticks, `$()`) are rejected outright rather than blocklisted — Anthropic's own security guidance for this tool says a blocklist is not sufficient. Confirmed live: the agent tried a piped `find ... | wc -l`, got rejected, and self-corrected to a plain `find` on the next turn.

Git and GitHub operations are hand-written calls for now, to keep the mechanics low-level and explainable; a later brick replaces them with the `gh` / `gog` CLI. `edit_file` went through the same fork `bash` already did: built on Anthropic's own `text_editor_20250728` (schema-less, `str_replace_based_edit_tool`) rather than hand-rolled — the ambiguous-match refusal above is that tool's own built-in behavior, not something we wrote. Two independent safety layers sit around it regardless of who wrote the edit mechanics: every path is resolved to canonical form and checked against the workspace root, and a path denylist blocks specific files even inside it.

## Code navigation & RAG

- **Code is navigated live, not vector-indexed.** The agent reads the repo on demand with the `bash` tool (Anthropic's `bash_20250124`, read-only allowlist) on the working checkout. On a single small repo this beats vector RAG: the reads are exact and current, follow imports, and never break on chunk boundaries the way code chunks do. A structural index (tree-sitter / ctags) or a codebase-graph service (Graphify-class platforms) is the productionization path if the repo grows — not needed at this size.
- **RAG is scoped to a prose knowledge base**, which is where semantic search actually earns its place (and the artifact the sprint asks for on Day 4) — not this repo's own docs alone, but a corpus of engineering good practices, SDLC, and methodology the agent consults *while* producing a PR (commit conventions, test-structure guidance, code-review checklists), so retrieval serves the north-star SLO directly instead of just satisfying a rubric line. This is a reversal from the original call (RAG scoped to this repo's own thin docs/issues): that corpus was genuinely too small to need semantic search over, and a corpus that exists only to satisfy the rubric line is worse than one the agent's own SLO can actually benefit from. `rag/ingest.py`'s `chunk_markdown()` splits on the document's own existing headings first, windowing only oversized sections — not fixed-size chunking, per Day 4's own 90-second-drill answer key: structure the author already put there is free retrieval metadata, and it makes a citation point at something findable. Retrieval is hybrid: FTS5/BM25 (exact terms, identifiers) fused with dense vector (paraphrase, synonymy) via Reciprocal Rank Fusion, not a weighted score sum — the two legs live on incomparable scales, and RRF only needs rank order. Grounding rule: refuse (`INSUFFICIENT_CONTEXT`, naming what was searched for) if no chunk scores above threshold τ — not yet calibrated; that happens against the 10-query smoke set (5 answerable / 3 unanswerable / 2 multi-hop) Day 4 sequences last, not guessed ahead of the real corpus. `chunk_file()` also handles PDF (`chunk_pdf()`, page-based windowing — verified live against two real reports, no font/heading detection available so it doesn't try for finer structure than the page). `rag/add_source.py` registers a new source (and, once `--reviewed`, ingests it) in one command, instead of hand-editing `data/kb/manifest.json` — the manifest is the license/PII tracking table itself, not a separate document (see `data/kb/manifest.example.json`, the committed template).

## Control points (local gates)

The CI is the oracle; the agent's job is to converge to green CI. The only local gate before `open_pr` is **running the tests**. Lint, type-check, and coverage stay CI-only for now — they are added as local gates later, and only if Day 9 failure-mode analysis shows they are top causes of first-attempt CI failures. We do not pre-add controls whose need we have not measured.

**Turn budget.** The edit→test loop is capped at `MAX_TURNS` (default 8) cycles. On exhaustion the agent stops, opens **no PR**, and posts a "could not resolve after N turns" comment via `comment_on_ticket`. It never ships a PR it could not get green — a failed run is a comment, not a broken draft left behind.

## Runtime & isolation

v1 is a single **Docker container** (the Day 6 deliverable). The container holds a checkout of the target repo and runs the whole loop in place — LLM calls, `edit_file`, `run_tests`, and git all execute inside it. Isolation between runs is a fresh git worktree (or clone) per ticket inside the container, and runs are serialized for the POC, so concurrency is not a concern yet.

This is deliberately the simpler, less-isolated option: it is exactly what Day 6 asks for (package the agent as a container) and it avoids an external-sandbox architecture we do not need yet.

The upgrade path — external per-run sandboxes, or the Claude Agent SDK / Claude Managed Agents' hosted sandboxes and ready-made base tools — is named as a fork under **Deferred architecture decisions** below. We graduate to it once the loop and the evals are solid, not before.

## SLOs

- **p95 latency:** ≤ 300 s per ticket→PR run (local test execution dominates).
- **cost/request:** ≤ $0.20 per run on the default model (`claude-haiku-4-5`); re-baseline when the model is raised.
- **grounded rate:** ≥ 95% (the edits touch only files/symbols that exist in the repo the agent actually read).
- **tool success rate:** ≥ 98% (tool calls that execute without error).
- **★ north-star:** ≥ 40% of generated PRs pass GitHub CI on the first attempt. This is the honest quality measure — the residual gap after the local `run_tests` gate is env divergence (local ≠ CI) plus CI-only gates (lint, type-check, coverage, integration). Days 7–9 push this number up.

## Shadow / rollout

- **Shadow mode replays history.** Instead of a percentage of live traffic (which does not map to an agent whose every output a human reviews), shadow runs the agent on issues that were **already resolved** and diffs the agent's PR against the human PR that actually merged. Zero production risk, and it is the baseline for the eval (Day 11 — diff against baseline and quantify value). Metrics: first-attempt CI pass, and how close the agent's change is to the human's.
- **Progressivity is autonomy per issue-class, not a traffic percentage.** As measured trust grows: (1) draft PR, human reviews everything, the agent never merges → (2) the agent marks the PR ready-for-review once CI is green → (3) auto-merge on green for a narrow, well-defined class (dependency bumps, small scoped tickets) → (4) widen the trusted classes. Kill switch: a label / env flag that instantly reverts everything to shadow (or off).

## Deferred architecture decisions

Real forks named now, each with a stated default (POC) and a stated trigger to revisit (production) — full design in [`docs/research/spec.md`](research/spec.md): execution isolation (Docker + serialized worktrees today), GitHub integration (hand-written REST today). `docs/research/rag.md` and `docs/research/secrets-redaction.md` cover the forks specific to those subsystems.

## Out of scope

The agent never touches these paths. A prompt instruction alone would be a suggestion, not a boundary — enforcement lives in `edit_file`'s path denylist, checked at the tool boundary (built Day 3), for the two that map to real, isolated paths:

1. Crypto changes — `crypto.py` denied entirely.
2. Database migrations — `migrations/` denied entirely.

**Auth is named in scope, and now enforced past what a path denylist alone can do.** Auth logic lives inside `app.py`, shared with unrelated code — no dedicated auth file exists for a path-level denylist to isolate, so "no auth changes" as a policy needed a different mechanism: `edit_file._touches_auth_symbol()` scans whatever text a write would add or remove for a name in `agent.config.AUTH_SENSITIVE_SYMBOLS` (e.g. `get_session_user`, `_is_cross_site`, `SESSION_COOKIE` — the reference target's own auth identifiers) and blocks the write if found, independent of which file it's in. Coach-flagged, then closed the same session — see `tools/edit_file.py`'s own comment for the reasoning and `evals/test_edit_file_tool.py` for the coverage (both directions: adding an auth symbol, and removing one).
