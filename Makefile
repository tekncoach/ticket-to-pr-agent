.PHONY: agent run run-ticket mcp-server ingest rag-query test eval golden golden-freeze golden-check judge-dump judge-calibrate docker-up docker-down

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

# Hand the agent a ticket — SPEC.md's POC trigger.
# Usage: make run-ticket ISSUE=13
run-ticket:
	uv run --env-file .env python -c "import json,urllib.request as u; \
	  r=u.urlopen(u.Request('http://127.0.0.1:8000/v1/run', \
	  json.dumps({'issue': $(ISSUE)}).encode(), \
	  {'content-type':'application/json'})); print(r.read().decode())"

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

# Run the golden set (evals/golden.jsonl) and write a scored report into
# evals/results/. Narrow it with TIER or SPLIT, or name cases with ID:
#   make golden TIER=retrieval          # free, no model
#   make golden TIER=single_turn        # the model deciding, nothing can write
#   make golden SPLIT=adversarial
#   make golden ID=ref-001 ID=tool-011
# agent_run cases are never started from here — dollars and minutes, on demand.
golden:
	uv run --env-file .env python -m evals.runner \
	  $(foreach t,$(TIER),--tier $(t)) \
	  $(foreach s,$(SPLIT),--split $(s)) \
	  $(foreach i,$(ID),--id $(i)) \
	  $(if $(MODEL),--model $(MODEL),)

# Rewrite evals/golden.lock.json from the set itself. Re-running it on an
# unchanged set is a no-op — the frozen date moves only when the bytes do,
# so the freeze never produces a diff of its own.
# VERSION=v2 bumps the version alongside the content.
golden-freeze:
	uv run python -m evals.freeze $(if $(VERSION),--version $(VERSION),)

# The judge protocol, in order — evals/JUDGE-CALIBRATION.md explains why.
# 1. dump writes evals/judge-sample.jsonl: question, evidence, answer, and no
#    model verdict. Re-running it invalidates existing labels on purpose.
judge-dump:
	uv run --env-file .env python -m evals.judge --dump

# 2. score each line 1-5 in evals/judge-labels.jsonl, by hand, before step 3.
# 3. calibrate runs the judge on that same sample and reports the agreement.
#    PASSES=5 runs it five times on the same labels and reports a range plus
#    the cases it could not settle — the judge is not deterministic, and one
#    draw is a number without error bars.
judge-calibrate:
	uv run --env-file .env python -m evals.judge --calibrate $(if $(PASSES),--passes $(PASSES),)

# Verify the lock without writing: non-zero if golden.jsonl has drifted from
# what was frozen, and it names which field moved.
golden-check:
	uv run python -m evals.freeze --check

# Build and run the service in Docker. The compose file does not exist
# yet — this target is a placeholder until deployment is built out.
# --env-file is not optional: compose looks for .env next to the compose file
# (deploy/), not at the repo root, so without it every secret interpolates to
# an empty string and the container comes up with no key at all.
docker-up:
	docker compose --env-file .env -f deploy/docker-compose.yml up --build

docker-down:
	docker compose --env-file .env -f deploy/docker-compose.yml down

