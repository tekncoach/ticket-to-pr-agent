# agent/service.py
#
# The FastAPI service — parity target: hello_agent.py's Day 2 /health +
# /v1/chat, rebuilt around the current agent/runtime.py instead of the
# single-tool Day 2 loop. Kept alongside agent/cli.py, not instead of it —
# both build their AgentRuntime from agent/factory.py.
#
# Run it:   uv run uvicorn agent.service:app --reload
# Health:   curl localhost:8000/health
# Chat:     curl -s localhost:8000/v1/chat -H 'content-type: application/json' \
#                 -d '{"message":"What time is it in Paris?"}'
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.factory import LLM_MODEL, SHADOW_MODE, TOOLS, build_runtime, llm_ready

app = FastAPI(title="ticket-to-pr-agent", version="0.1.0")

# One shared AgentRuntime for the process lifetime, not one per request —
# same reasoning as __post_init__'s own client caching: the SDK client
# holds a connection pool, no reason to rebuild it (or re-validate the
# thinking config) on every call. run() generates a fresh run_id per call
# regardless, so sharing the instance across requests is safe.
_runtime = build_runtime()


class ChatRequest(BaseModel):
    # Bounded to guard the stated cost/latency SLO — an unbounded prompt is
    # a blank cheque to messages.create. Carried over from hello_agent.py;
    # this project's own AgentRuntime had no equivalent guard until now.
    message: str = Field(..., max_length=8000)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "shadow_mode": SHADOW_MODE,
        # hello_agent.py hardcoded this False ("no write tools yet"). Real
        # now: edit_file is side_effect=True and genuinely gated by
        # SHADOW_MODE — true reflects whether shadow mode is actually
        # doing something, not just declared.
        "shadow_enforced": SHADOW_MODE and any(t.side_effect for t in TOOLS.values()),
        "llm_ready": llm_ready(),
        "model": LLM_MODEL,
        "tools": sorted(TOOLS.keys()),
    }


@app.post("/v1/chat")
def chat(req: ChatRequest):
    if not llm_ready():
        return JSONResponse(
            status_code=503,
            content={"error": "LLM_API_KEY (or ANTHROPIC_API_KEY) is not set"},
        )
    return _runtime.run(req.message)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
