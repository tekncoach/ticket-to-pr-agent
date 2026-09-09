.PHONY: agent run mcp-server ingest eval docker-up

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

# Ingest the liberty-rider corpus into the vector store (real on Day 4).
ingest:
	uv run python -m rag.ingest --path data/corpus

# Run the unit / regression suite. Runs without an LLM key.
eval:
	uv run pytest evals -q

# Day 6: build and run the service in Docker. The compose file does not
# exist yet — this target is a placeholder until Day 6 owns deployment.
docker-up:
	docker compose -f deploy/docker-compose.yml up --build
