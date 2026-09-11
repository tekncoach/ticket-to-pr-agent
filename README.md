# ticket-to-pr-agent

A coding agent that turns a labeled GitHub Issue into a tested, CI-ready pull request — built directly on Anthropic's Messages API, with no agent framework in between.

[![CI](https://github.com/tekncoach/ticket-to-pr-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/tekncoach/ticket-to-pr-agent/actions/workflows/ci.yml) ![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue) ![License: MIT](https://img.shields.io/badge/license-MIT-green)

## What it does

Point the agent at a repo and a labeled issue. It reads the ticket, explores the codebase, makes the change, runs the test suite locally, and opens a draft pull request — reporting the outcome back as a comment on the issue. Every write action stays behind a mode flag until you decide to trust it: shadow mode by default, live writes only when you flip it.

The target repo is a config value, not a hardcoded assumption — point `TARGET_REPO` at any repo you have a token for. Development and every recorded scenario in this repo used [`liberty-rider-myroadtrips`](https://github.com/tekncoach/liberty-rider-myroadtrips) as the reference target.

## Why this exists

Most "agent" demos wrap an LLM call in a chat loop and call it done. This one is built the other way: every mechanism an FDE-style deployment actually needs — structured tool calls, write gating, argument validation, cost and token accounting, crash-safe logging — is hand-rolled and verified against the live API, not assumed to come free from a framework.

- **No agent framework.** The tool-calling loop is built directly on `anthropic.messages.create` — no LangChain, no LangGraph. Every retry, stop condition, and failure path is code you can read start to finish in one file.
- **Native tools where they fit, hand-rolled where it matters.** File exploration and edits run on Anthropic's own `bash_20250124` and `text_editor_20250728` client-side tools — schema-less, security-hardened at the boundary (an executable allowlist, never `shell=True`, path confinement to the target checkout, a path denylist for sensitive files). GitHub calls stay hand-written REST, deliberately, to keep the mechanics visible.
- **Policy guards the model can't opt out of.** A hard cap on parallel tool calls, JSON-Schema-validated arguments on every custom tool, a mode flag that disables every write tool at once, and a hard stop the instant the model repeats an identical tool call — converting a possible infinite spin into a bounded, explainable failure.
- **Full run observability.** Every tool call, token count (including thinking tokens), USD cost, and stop reason is written to an append-only JSONL log per run — flushed and fsynced per event, so a mid-run crash doesn't lose what already happened. A second, parallel JSONL file per run carries the actual conversation content (what was asked, what the model said or thought, what each tool returned) — kept separate so the lean metrics log stays scannable on its own. An optional live mode prints the same events to stdout as they occur.
- **A written spec that evolves with the code.** [`docs/SPEC.md`](docs/SPEC.md) states the problem, the tools, the SLOs, and every architecture decision with its trigger to revisit — including the ones later commits reversed, on purpose, once real usage justified it.

## How it works

```
fetch_ticket → explore (bash) → edit_file → run_tests
                                      ↑           │
                                      └── retry ──┘ (until green, or MAX_TURNS)
                                                  │
                       git_commit → git_push → open_pr → get_ci_status → comment_on_ticket
```

The first four stages are built and tested against a live target repo; the rest is the named next milestone. See [`docs/SDLC-schema.md`](docs/SDLC-schema.md) for the full diagram, including the production-pipeline reference steps (lint, type-check) this project isn't running locally yet, and why.

## Quickstart

```bash
# Install dependencies
uv sync --extra dev

# Optional but recommended: betterleaks, for redacting secrets found in
# fetched ticket content (an external binary, not a Python package —
# see docs/SECRETS-REDACTION.md). Without it, fetch_ticket still works,
# with narrower redaction coverage.
brew install betterleaks   # or the Linux equivalent

# Configure — copy the template and fill in real values (.env is gitignored)
cp .env.example .env
$EDITOR .env   # LLM_API_KEY, GITHUB_TOKEN, TARGET_REPO

# Run it
uv run --env-file .env python -m agent.cli "What does GitHub issue #1 ask for?"

# Watch it live instead of waiting for the final answer
LIVE_TRACE=true uv run --env-file .env python -m agent.cli "..."

# RAG: same template pattern as .env — the real manifest names local
# machine paths (some outside this repo entirely) and is gitignored.
cp data/kb/manifest.example.json data/kb/manifest.json
# edit it to point at your own corpus, then:
make ingest
make rag-query Q="a question about what you just ingested"
```

Nothing writes to the target repo until `SHADOW_MODE=false` is set explicitly — the default is read-only by design.

## Project layout

```
agent/
  runtime.py     the agent loop: tool dispatch, policy guards, thinking, cost tracking
  cli.py         entrypoint — build an AgentRuntime, run one message
  config.py      target repo, workspace path, session log location — env-configurable
  event_sink.py  where trace events go: a JSONL file, live stdout, both, or neither (tests)
tools/
  bash.py         Anthropic's native bash tool, read-only allowlist + safe pipelining
  edit_file.py    Anthropic's native text-editor tool, workspace-confined + denylisted
  fetch_ticket.py hand-written GitHub REST call
docs/            the technical spec, architecture decisions, and everything verified live
evals/           tests
```

## Testing

```bash
uv run pytest evals -q
```

## Documentation

- [`docs/SPEC.md`](docs/SPEC.md) — problem, users, tools, SLOs, rollout plan, and every deferred architecture decision
- [`docs/SDLC-schema.md`](docs/SDLC-schema.md) — the full build-to-ship pipeline, what's built vs. planned
- [`docs/manual_scenarios.md`](docs/manual_scenarios.md) — five live-run scenarios, including a forced refusal and a forced failure
- [`docs/CLAUDE-CLIENT-SIDE-TOOLS.md`](docs/CLAUDE-CLIENT-SIDE-TOOLS.md) — reference for Anthropic's native tool types
- [`docs/CLAUDE-USAGE-AND-THINKING.md`](docs/CLAUDE-USAGE-AND-THINKING.md) — the full API usage object, verified by inspection, and how extended thinking is wired in
- [`docs/MCP-SERVER.md`](docs/MCP-SERVER.md) — exposing `fetch_ticket` over MCP, and the per-user rights design for when that's actually needed
- [`docs/SECRETS-REDACTION.md`](docs/SECRETS-REDACTION.md) — why untrusted fetched content is scanned for secrets before it reaches the model or the logs
- [`docs/RAG-CONTEXT-EXPANSION.md`](docs/RAG-CONTEXT-EXPANSION.md) — parent-document expansion (built), and two more patterns named but not built yet

## Status

Proof of concept, under active development. Ticket intake, codebase exploration, and file editing are built and verified against a live target repo and a live GitHub API. Git operations, PR creation, CI status polling, and issue comments are specified but not yet built — see [`docs/SDLC-schema.md`](docs/SDLC-schema.md) for the exact line. CI (`.github/workflows/ci.yml`) runs the full test suite on every push and pull request — no secrets required, every test is hermetic.

## License

MIT — see [`LICENSE`](LICENSE).
