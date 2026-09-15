.PHONY: agent run run-ticket mcp-server ingest rag-query test eval golden golden-ci golden-record golden-replay golden-freeze golden-check modes drift judge-dump judge-calibrate hooks docker-up docker-down

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

# Run the golden set, measure it, compare it to evals/gates.yaml, and exit
# non-zero on a breach. Thresholds read the LOWER bound of a range, so
# PASSES=3 makes the gate stricter, not noisier.
#   make golden TIER=retrieval          # free, no model — the PR gate
#   make golden TIER=single_turn PASSES=3
#   make golden SPLIT=adversarial
#   make golden ID=ref-001 ID=tool-011
#   make golden NO_GATE=1               # measure and report, always exit 0
#   make golden TIER=single_turn JUDGE=1  # grade faithfulness too (a call per case)
# agent_run cases are never started from here — dollars and minutes, on demand.
golden:
	uv run --env-file .env python -m evals.run \
	  $(foreach t,$(TIER),--tier $(t)) \
	  $(foreach s,$(SPLIT),--split $(s)) \
	  $(foreach i,$(ID),--id $(i)) \
	  $(if $(PASSES),--passes $(PASSES),) \
	  $(if $(NO_GATE),--no-gate,) \
	  $(if $(JUDGE),--judge,) \
	  $(if $(GATES),--gates $(GATES),) \
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

# The gate CI runs: the retrieval cases against the committed CI corpus, with
# no key and no network. BM25 only — see rag/retrieve.py — so it is held to its
# own measured bar rather than the full corpus's.
golden-ci:
	VECTOR_DB_PATH=data/kb-ci/kb.sqlite3 EVAL_RESULTS_DIR=$${EVAL_RESULTS_DIR:-$$(mktemp -d)} \
	  uv run python -m evals.run --tier retrieval --gates ci_retrieval

# Compare the latest run to evals/results/baseline.json. Ranges, not points:
# a drop counts only when the two do not overlap, because a single case here
# has scored 0.00 and 1.00 on consecutive passes.
#   make drift FAIL=1   exit non-zero on drift
drift:
	uv run python -m evals.drift $(if $(FAIL),--fail-on-drift,)

# The failure-mode sheet. No argument: what is open, closed and accepted.
#   make modes CHECK=1    every closed mode names a test that exists
#   make modes FROM_RUN=1 failures in the latest run no row covers, as CSV rows
modes:
	uv run python -m evals.promote $(if $(CHECK),--check,) $(if $(FROM_RUN),--from-run,)

# Freeze each run into evals/traces/ so CI can re-score it. Run where the
# corpus is; commit what it writes.
#   make golden-record TIER=retrieval
golden-record:
	uv run --env-file .env python -m evals.run --record --no-gate \
	  $(foreach t,$(TIER),--tier $(t)) $(foreach i,$(ID),--id $(i))

# Re-score those frozen runs against the current scorers and thresholds. No
# model, no corpus, no secrets — this is the one behavioural gate CI can run.
# It catches a scorer or threshold regression, NOT an agent regression.
golden-replay:
	uv run python -m evals.replay

# Install scripts/pre-push as the local gate. CI runs the hermetic half; the
# eval half needs the corpus and the target checkout, which a stateless runner
# does not have — see evals/README.md.
hooks:
	install -m 755 scripts/pre-push .git/hooks/pre-push
	@echo "installed .git/hooks/pre-push"

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

