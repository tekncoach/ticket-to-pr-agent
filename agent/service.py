# agent/service.py
#
# The FastAPI service — /health + /v1/chat around the current
# agent/runtime.py. Kept alongside agent/cli.py, not instead of it —
# both build their AgentRuntime from agent/factory.py.
#
# Run it:   uv run uvicorn agent.service:app --reload
# Health:   curl localhost:8000/health
# Chat:     curl -s localhost:8000/v1/chat -H 'content-type: application/json' \
#                 -d '{"message":"What time is it in Paris?"}'
from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agent.config import shadow_mode
from agent.factory import LLM_MODEL, TOOLS, build_runtime, llm_ready
from agent.runtime import AgentRuntime

app = FastAPI(title="ticket-to-pr-agent", version="0.1.0")


@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    rid = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = rid
    resp = await call_next(request)
    resp.headers["x-request-id"] = rid
    return resp

# One shared AgentRuntime for the process lifetime, not one per request —
# same reasoning as __post_init__'s own client caching: the SDK client
# holds a connection pool, no reason to rebuild it (or re-validate the
# thinking config) on every call. run() generates a fresh run_id per call
# regardless, so sharing the instance across requests is safe.
# Built on first use, not at import. A missing LLM_API_KEY used to raise
# here, so the process died before it could serve anything — including
# /health, which is the one endpoint an operator needs when a secret is
# missing. It also made /v1/chat's own 503-on-no-key branch unreachable. A
# container that starts and reports itself unhealthy beats one that
# crash-loops with the reason only in the logs.
_runtime: AgentRuntime | None = None


def _get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


class ChatRequest(BaseModel):
    # Bounded to guard the stated cost/latency SLO — an unbounded prompt is
    # a blank cheque to messages.create. Carried over from hello_agent.py;
    # this project's own AgentRuntime had no equivalent guard until now.
    message: str = Field(..., max_length=8000)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        # Read on every request, not cached at import: this is the field an
        # operator refreshes to confirm the kill switch actually took.
        "shadow_mode": shadow_mode(),
        # hello_agent.py hardcoded this False ("no write tools yet"). Real
        # now: edit_file is side_effect=True and genuinely gated by
        # True reflects whether shadow mode is actually doing something, not
        # just declared: it is only meaningful if a write tool exists to gate.
        "shadow_enforced": shadow_mode() and any(t.side_effect for t in TOOLS.values()),
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
    return _get_runtime().run(req.message)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
