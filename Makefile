.PHONY: run ingest eval docker-up

# Start the FastAPI service locally with autoreload.
run:
	uv run uvicorn hello_agent:app --reload

# Ingest the liberty-rider corpus into the vector store (real on Day 4).
ingest:
	uv run python -m rag.ingest --path data/corpus

# Run the eval / regression suite. Runs without an LLM key.
eval:
	uv run pytest evals -q

# Build and run the service in Docker (compose file lands on Day 6).
docker-up:
	docker compose -f deploy/docker-compose.yml up --build
