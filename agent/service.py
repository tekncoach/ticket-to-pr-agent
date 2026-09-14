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

import json
import re
import uuid

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from agent.config import SESSIONS_DIR, shadow_mode
from agent.errors import ErrorClass, classify
from agent.tickets import READY_LABEL, check_ready, list_issues, task_prompt
from agent.factory import LLM_MODEL, TOOLS, build_runtime, llm_ready
from agent.runtime import AgentRuntime

# How a run ended, in the trace's own vocabulary. "incomplete" is what a
# crashed or still-running run looks like, and saying so beats implying it
# finished.
_TERMINAL_EVENTS = {
    "final", "auth_failure", "repeated_tool_failure",
    "duplicate_call_stop", "llm_call_error",
}

app = FastAPI(title="ticket-to-pr-agent", version="0.1.0")


@app.middleware("http")
async def request_id_mw(request: Request, call_next):
    """One id from the request header to the trace file and back.

    The starter shape tagged the HTTP request; this binds that tag to the
    run_id AgentRuntime uses, so the header a caller sees is also the name of
    the trace they can replay. Truncated to run_id's own width because it
    becomes a filename, and a caller-supplied header is untrusted input: it is
    filtered to hex so nothing reaches the path built from it.
    """
    supplied = request.headers.get("x-request-id", "")
    rid = _safe_run_id(supplied) or uuid.uuid4().hex[:12]
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


_RUN_ID_RE = re.compile(r"^[0-9a-f]{1,32}$")


def _safe_run_id(value: str) -> str | None:
    """A run_id becomes a filename, so it never carries anything but hex.

    This is the guard on /v1/trace/{run_id} as much as on the header: without
    it, "../../etc/passwd" is a path, not an identifier.
    """
    value = (value or "").strip().lower()[:32]
    return value if _RUN_ID_RE.match(value) else None


class ChatRequest(BaseModel):
    # Bounded to guard the stated cost/latency SLO — an unbounded prompt is
    # a blank cheque to messages.create. Carried over from hello_agent.py;
    # this project's own AgentRuntime had no equivalent guard until now.
    message: str = Field(..., max_length=8000)


_INDEX = Path(__file__).parent / "static" / "index.html"


def _conversation(events: list[dict]) -> tuple[str | None, str | None]:
    """(what was asked, what was finally answered), from the run's own stream.

    The answer is the text of the last assistant turn — the one that stopped
    asking for tools. Reading the last text block regardless of position would
    pick up the model's narration between tool calls instead.
    """
    asked = answer = None
    for message in (e for e in events if e.get("event") == "message"):
        content, role = message.get("content"), message.get("role")
        if role == "user" and asked is None and isinstance(content, str):
            asked = content
        if role == "assistant" and isinstance(content, list):
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            has_tool_use = any(b.get("type") == "tool_use" for b in content)
            if text and not has_tool_use:
                answer = text
    return asked, answer


def _read_events(path: Path) -> list[dict]:
    """A trace file's events. A half-written final line is what a crash
    mid-run looks like — serving the rest beats serving nothing, and a run
    ending without a final event is itself the finding."""
    events = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """The demo page — one file, no build step, served from the same process.

    Read per request rather than cached: the page is small, and editing it
    without restarting the service is worth more than the microseconds.
    Carries noindex here as well as in the document, since a demo URL handed
    to one interviewer has no business in a search index.
    """
    return HTMLResponse(
        _INDEX.read_text(),
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


# Served from a route rather than a data: URI in the page. The data URI form
# was tried and silently failed — raw spaces in the SVG left the browser unable
# to parse it, so it fell back to /favicon.ico and kept 404ing. A route cannot
# fail that way, and a 404 in the console is what an interviewer sees the
# moment they open devtools.
_FAVICON = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
    "<text y='13' font-size='13'>&#10003;</text></svg>"
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(_FAVICON, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/v1/runs")
def runs(limit: int = 25):
    """Recent runs, newest first — the index the trace view needs to be usable.

    Without it a run id is only reachable if you kept the response that
    produced it, which makes "paste this and replay the session" true only for
    the session you are already looking at.

    Read from the trace files themselves rather than a separate index: the
    files are the record, and a second store would be one more thing to keep
    in sync with them.
    """
    if not SESSIONS_DIR.exists():
        return {"runs": []}

    files = sorted(
        SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True,
    )[:max(1, min(limit, 100))]

    out = []
    for path in files:
        events = _read_events(path)
        if not events:
            continue
        calls = [e for e in events if e.get("event") == "tool_result"]
        asked, _ = _conversation(events)
        out.append({
            "run_id": path.stem,
            "at": events[0].get("ts"),
            # What the run was asked, so the history reads as a list of
            # questions rather than a list of hex ids.
            "asked": asked,
            "outcome": next(
                (e["event"] for e in reversed(events) if e.get("event") in _TERMINAL_EVENTS),
                "incomplete",
            ),
            "tool_calls": len(calls),
            "failed_tool_calls": sum(1 for e in calls if not e.get("ok")),
            "cost_usd": sum(e.get("cost_usd") or 0 for e in events) or None,
        })
    return {"runs": out}


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
def chat(req: ChatRequest, request: Request):
    if not llm_ready():
        return JSONResponse(
            status_code=503,
            content={"error": "LLM_API_KEY (or ANTHROPIC_API_KEY) is not set"},
        )
    return _get_runtime().run(req.message, run_id=request.state.request_id)


class RunRequest(BaseModel):
    issue: int = Field(..., ge=1, description="The GitHub Issue number to work.")


@app.get("/v1/issues")
def issues(ready_only: bool = False):
    """The backlog, each issue flagged with whether the agent may work it.

    Unfiltered by default: a queue narrowed to the allowed rows hides the
    contract, while one that marks them shows it — and clicking a row without
    the label is how you watch /v1/run refuse.
    """
    result = list_issues(ready_only=ready_only)
    if not result.ok:
        return JSONResponse(status_code=502, content={"error": result.error_code})
    return {"label": READY_LABEL, "issues": result.data}


@app.post("/v1/run")
def run_ticket(req: RunRequest, request: Request):
    """Hand the agent a ticket number — SPEC.md's POC trigger.

    Synchronous, and deliberately so: no job queue today. A caller who wants
    to watch the run rather than wait for it supplies its own x-request-id and
    polls /v1/trace/{that id} while this request is still open — the trace is
    flushed line by line as it happens, so it is readable before the run ends.
    That is what lets a page show progress without any queue behind it.
    """
    if not llm_ready():
        return JSONResponse(
            status_code=503,
            content={"error": "LLM_API_KEY (or ANTHROPIC_API_KEY) is not set"},
        )

    # The label is the contract, checked before the model sees anything. An
    # agent cannot be allowed to reason its way past the question of whether
    # it should be running at all.
    ready = check_ready(req.issue)
    if not ready.ok:
        status = 403 if classify(ready.error_code) is ErrorClass.DENIED else 502
        return JSONResponse(status_code=status, content={"error": ready.error_code})

    result = _get_runtime().run(task_prompt(req.issue), run_id=request.state.request_id)
    return {"issue": ready.data, **result}


@app.get("/v1/trace/{run_id}")
def trace(run_id: str):
    """Replay a past run from its id.

    This is the endpoint that turns a bad answer in front of an interviewer
    into the strongest moment of the demo: paste the id from the response
    header, read what the agent actually did, turn by turn, with each tool's
    outcome, error class and duration. Debugging in someone else's
    environment is the job.
    """
    safe = _safe_run_id(run_id)
    if safe is None:
        return JSONResponse(status_code=400, content={"error": "malformed run_id"})

    path = SESSIONS_DIR / f"{safe}.jsonl"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": f"no trace for run {safe}"})

    events = _read_events(path)
    calls = [e for e in events if e.get("event") == "tool_result"]
    asked, answered = _conversation(events)
    if answered is None:
        # A run the runtime stopped never produced an assistant turn, but it
        # did produce a sentence — carried on the terminal event.
        answered = next(
            (e.get("answer") for e in reversed(events)
             if e.get("event") in _TERMINAL_EVENTS and e.get("answer")),
            None,
        )
    return {
        "run_id": safe,
        # The events file records what the agent DID; the question it was
        # asked and the answer it gave live in the messages file beside it.
        # Serving only the events made a replayed run show its steps and hide
        # its point — "paste this id and replay the session" has to include
        # what the session actually said.
        "asked": asked,
        "answer": answered,
        "events": events,
        "summary": {
            "turns": len({e.get("turn") for e in events if e.get("turn") is not None}),
            "tool_calls": len(calls),
            "failed_tool_calls": sum(1 for e in calls if not e.get("ok")),
            "cost_usd": sum(e.get("cost_usd") or 0 for e in events) or None,
            # Occupancy at the last model call, not the sum of every turn:
            # spend accumulates, the window does not.
            "context_pct": next(
                (round(100 * e["context_tokens"] / e["context_window"])
                 for e in reversed(events)
                 if e.get("context_tokens") and e.get("context_window")),
                None,
            ),
            "outcome": next(
                (e["event"] for e in reversed(events)
                 if e.get("event") in _TERMINAL_EVENTS),
                "incomplete",
            ),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
