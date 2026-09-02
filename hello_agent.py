"""Day 2 hello-agent — a single-file, tool-using agent behind FastAPI.

Deliberately ONE file: this is the first POC. Later days decompose it into
agent/, tools/, rag/. It already has everything the Day 2 deliverable asks for:

- one tool (`get_time`)
- a plain function-calling agent loop (raw Anthropic SDK, no framework)
- a JSON response over `POST /v1/chat`
- a healthcheck at `GET /health`
- one structured JSON log line per turn (so Days 5-8 are debuggable)

Run it:   make run          (uv run uvicorn hello_agent:app --reload)
Health:   curl localhost:8000/health
Chat:     curl -s localhost:8000/v1/chat -H 'content-type: application/json' \
                -d '{"message":"What time is it in Paris?"}'
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# --------------------------------------------------------------------------- #
# Config — read once from the environment (.env is loaded by `uv run`/uvicorn
# only if you export it; for a POC we read plain env vars).
# --------------------------------------------------------------------------- #
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1024"))
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
MAX_TURNS = 8

SYSTEM_PROMPT = (
    "You are a coding agent that will grow into a ticket->PR agent. For now the "
    "only thing you can do is tell the time: call the get_time tool when asked "
    "about the current time. Be concise."
)

# --------------------------------------------------------------------------- #
# Structured logging — one JSON line per event. Everything after Day 3 is
# debugging a loop you cannot see; this is the cheapest thing that makes it
# visible.
# --------------------------------------------------------------------------- #
_log = logging.getLogger("hello_agent")
if not _log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(LOG_LEVEL.upper())
    _log.propagate = False


def log_event(event: str, *, trace_id: str, **fields) -> None:
    _log.info(
        json.dumps(
            {"ts": round(time.time(), 3), "event": event, "trace_id": trace_id, **fields},
            default=str,
        )
    )


# --------------------------------------------------------------------------- #
# The one tool: get_time. Deterministic and side-effect free.
# --------------------------------------------------------------------------- #
def get_time(arguments: dict) -> str:
    tz_name = arguments.get("timezone", "UTC")
    try:
        tz = timezone.utc if tz_name == "UTC" else ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return f"Error: unknown timezone {tz_name!r}."
    return datetime.now(tz).isoformat()


TOOLS = [
    {
        "name": "get_time",
        "description": "Return the current time as an ISO-8601 timestamp in the given IANA timezone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name, e.g. 'Europe/Paris'. Defaults to UTC.",
                }
            },
            "required": [],
            "additionalProperties": False,
        },
    }
]
TOOL_HANDLERS = {"get_time": get_time}


# --------------------------------------------------------------------------- #
# The plain function-calling loop — we own every step. This is the mechanism
# Days 3 and 5 build on.
# --------------------------------------------------------------------------- #
def run_agent(user_message: str, *, trace_id: str | None = None) -> dict:
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set.")

    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    trace_id = trace_id or uuid.uuid4().hex[:12]
    messages: list[dict] = [{"role": "user", "content": user_message}]
    tool_calls: list[str] = []

    log_event("turn.start", trace_id=trace_id, model=LLM_MODEL, shadow=SHADOW_MODE)

    for turn in range(1, MAX_TURNS + 1):
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        log_event(
            "turn.model",
            trace_id=trace_id,
            turn=turn,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        if response.stop_reason != "tool_use":
            text = next((b.text for b in response.content if b.type == "text"), "")
            log_event("turn.end", trace_id=trace_id, turns=turn, tool_calls=tool_calls)
            return {"text": text, "trace_id": trace_id, "turns": turn, "tool_calls": tool_calls}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls.append(block.name)
            try:
                output = TOOL_HANDLERS[block.name](dict(block.input))
                is_error = False
            except Exception as exc:  # a tool error is a result, not a crash
                output, is_error = f"Error: {exc}", True
            log_event("tool.result", trace_id=trace_id, turn=turn, tool=block.name, is_error=is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

    log_event("turn.exhausted", trace_id=trace_id, turns=MAX_TURNS, tool_calls=tool_calls)
    return {
        "text": "Stopped: hit the max turn budget without a final answer.",
        "trace_id": trace_id,
        "turns": MAX_TURNS,
        "tool_calls": tool_calls,
    }


# --------------------------------------------------------------------------- #
# The service.
# --------------------------------------------------------------------------- #
app = FastAPI(title="hello-agent", version="0.1.0")


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "shadow_mode": SHADOW_MODE,
        "llm_ready": bool(LLM_API_KEY),
        "model": LLM_MODEL,
    }


@app.post("/v1/chat")
def chat(req: ChatRequest):
    if not LLM_API_KEY:
        return JSONResponse(
            status_code=503,
            content={"error": "LLM_API_KEY (or ANTHROPIC_API_KEY) is not set"},
        )
    return run_agent(req.message)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
