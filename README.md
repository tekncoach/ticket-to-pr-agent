# hello-agent

Day 2 of the A10X 14-day sprint — the foundation for a **ticket → PR coding
agent** aimed at Cognition-style FDE loops. This repo is the "hello world": a
production-shaped scaffold, a one-page spec, and a runnable tool-using agent you
can hit over HTTP.

The end goal (Days 3–14) is an agent that turns a GitHub Issue on
`tekncoach/liberty-rider-myroadtrips` into a pull request that passes CI. Today
it only tells the time — but through the exact loop the real agent will use.

## Stack

- **Python 3.12+**, managed with [`uv`](https://docs.astral.sh/uv/)
- **Anthropic SDK** (raw Messages API) — we hand-write the agent loop, no
  framework, so the mechanism stays ours (that is what Days 3 & 5 build on)
- **FastAPI** + uvicorn for the service
- Model: `claude-haiku-4-5` by default, configurable via `LLM_MODEL`
- `pgvector` for retrieval (wired on Day 4)

See [`docs/SPEC.md`](docs/SPEC.md) for the full technical spec (problem, users,
tools, RAG, SLOs, rollout).

## Quickstart

```bash
# 1. Install dependencies
uv sync

# 2. Configure — copy the template and paste your key (.env is gitignored)
cp .env.example .env
$EDITOR .env                 # set LLM_API_KEY

# 3. Run the service
set -a && source .env && set +a
make run                     # http://127.0.0.1:8000

# 4. In another terminal, run the smoke test
./evals/tests.sh
```

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| `GET`  | `/health`  | Liveness + config; needs no key |
| `POST` | `/v1/chat` | Runs the agent loop; returns `{text, trace_id, turns, tool_calls}` |

```bash
curl -s localhost:8000/v1/chat -H 'content-type: application/json' \
     -d '{"message":"What time is it in Paris?"}'
```

Every turn emits one structured JSON log line (`turn.start`, `turn.model`,
`tool.result`, `turn.end`) so the loop is debuggable from Day 1.

## Layout

```
hello_agent.py     single-file agent: config, get_time tool, loop, FastAPI service
docs/SPEC.md       one-page technical spec
evals/tests.sh     HTTP smoke test
Makefile           run · ingest · eval · docker-up
agent/ tools/ rag/ reserved for the decomposition on Days 3+
```

The agent is one file on purpose — it is the first POC. Later days decompose it
into `agent/`, `tools/`, and `rag/`, add real GitHub tools, RAG over the
codebase, an eval suite, and a shadow rollout.
