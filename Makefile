.PHONY: agent run mcp-server ingest rag-query test eval docker-up

# Run the agent directly (agent/cli.py) with one message — the fast path,
# no server. Needs .env — see README Quickstart.
# Usage: make agent MSG="What does issue #1 ask for?"
agent:
	uv run --env-file .env python -m agent.cli "$(MSG)"

# Start the HTTP service (agent/service.py): GET /health, POST /v1/chat.
# Same AgentRuntime as `make agent` — agent/factory.py builds both.
run:
	uv run --env-file .env uvicorn agent.service:app --reload

# Start the MCP server exposing fetch_ticket — unrelated to agent/runtime.py,
# see docs/MCP-SERVER.md. Listens on http://127.0.0.1:8765/mcp.
mcp-server:
	uv run --env-file .env python -m agent.mcp_server

# Ingest every data/kb/manifest.json entry into the vector + FTS store.
# Needs .env (HF_TOKEN) — see docs/. The corpus is engineering
# good-practices content, not the target repo.
ingest:
	uv run --env-file .env python -m rag.build_corpus

# Manually explore search_kb: `make rag-query Q="your question"`, or with
# no Q, drops into a loop that reads one question per line.
rag-query:
	uv run --env-file .env python -m rag.query "$(Q)"

# The unit suite: deterministic, hermetic, free, and the CI gate. Runs
# without an LLM key or a network. This is the one that must be green.
test:
	uv run pytest tests -q

# The evals: the agent's own behaviour, measured against a real model and a
# real corpus. Costs money, is not deterministic, and is scored rather than
# passed — a threshold, not a green tick. Needs .env (LLM_API_KEY, HF_TOKEN)
# and a built corpus; skips what it cannot reach instead of failing.
eval:
	uv run --env-file .env pytest evals -q -rs

# Build and run the service in Docker. The compose file does not exist
# yet — this target is a placeholder until deployment is built out.
docker-up:
	docker compose -f deploy/docker-compose.yml up --build

