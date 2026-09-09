.PHONY: agent ingest eval docker-up

# Run the agent (agent/cli.py) with one message. Needs .env — see README
# Quickstart. Usage: make agent MSG="What does issue #1 ask for?"
agent:
	uv run --env-file .env python -m agent.cli "$(MSG)"

# Ingest the liberty-rider corpus into the vector store (real on Day 4).
ingest:
	uv run python -m rag.ingest --path data/corpus

# Run the unit / regression suite. Runs without an LLM key.
eval:
	uv run pytest evals -q

# Day 6: build and run the agent as a service in Docker, with an HTTP
# entrypoint (FastAPI wiring around agent/runtime.py — not built yet; the
# Day 2 hello_agent.py service this used to point to was retired once the
# Day 3 decomposition made it redundant, see git tag day2-hello-agent).
# The compose file does not exist yet either — this target is a placeholder
# until Day 6 owns deployment.
docker-up:
	docker compose -f deploy/docker-compose.yml up --build
