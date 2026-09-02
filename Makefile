.PHONY: run ingest eval smoke docker-up

# Start the FastAPI service locally with autoreload.
run:
	uv run uvicorn hello_agent:app --reload

# Ingest the liberty-rider corpus into the vector store (real on Day 4).
ingest:
	uv run python -m rag.ingest --path data/corpus

# Run the unit / regression suite. Runs without an LLM key.
eval:
	uv run pytest evals -q

# Smoke-test the running service end to end (needs a live LLM key + `make run`).
smoke:
	./evals/tests.sh

# Day 6: build and run the service in Docker. The compose file does not exist
# yet — this target is a placeholder until Day 6 owns deployment.
docker-up:
	docker compose -f deploy/docker-compose.yml up --build
