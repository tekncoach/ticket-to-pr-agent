# agent/event_sink.py
#
# Where AgentRuntime.run() sends each trace event — extracted out of
# runtime.py so the agent loop doesn't need to know anything about files,
# paths, or stdout. Two concrete reasons this earned its own abstraction
# now rather than staying inline:
#
#   1. Every test that calls run() was writing a real file to
#      tmp/sessions/ — a side effect with no way to opt out. NullSink
#      exists so tests can inject silence instead.
#   2. hello_agent.py's own log_event() prints structured JSON to stdout
#      live, specifically "to debug a loop you cannot see" — a real,
#      cheap technique worth having here too, without hardcoding it as
#      the only option. StdoutSink adds it; MultiSink combines it with
#      JSONLFileSink when both are wanted.
from __future__ import annotations

import json
import os
from pathlib import Path

from agent.config import SESSIONS_DIR


class EventSink:
    """Base class: does nothing. The default no-op, and the interface
    every sink below implements.

    ONE stream per run. This used to be two — metrics in one file,
    conversation content in another — on the argument that mixing large text
    into a lean trace makes it harder to scan. That optimises for grepping
    metrics at the cost of understanding a session, and understanding a
    session is what this is for: reconstructing what happened meant joining
    two files by hand, and the answer a run gave was invisible from the file
    that recorded what it did.

    It is also not how the field does it. OpenTelemetry's GenAI semantic
    conventions carry the conversation as attributes ON the span —
    `gen_ai.input.messages`, `gen_ai.output.messages` — not as a parallel
    stream, and Langfuse, Phoenix, Braintrust and W&B all ingest that shape.
    Separating metrics from content is a retention decision, and it belongs at
    read time (filter by event type), not at write time.

    emit_message remains as a thin alias so callers keep their intent legible
    at the call site; both land in the same ordered stream."""

    def emit(self, run_id: str, event: dict) -> None:
        pass

    def emit_message(self, run_id: str, message: dict) -> None:
        self.emit(run_id, message)


class NullSink(EventSink):
    """For tests: run() still calls emit()/emit_message() on everything,
    nothing is ever written anywhere."""


class JSONLFileSink(EventSink):
    """Appends to <sessions_dir>/<run_id>.jsonl — one file per run, read top
    to bottom as the session. flush + fsync per line, not buffered: a crash
    mid-run must not lose the turns that already succeeded, and that is also
    what lets the demo page poll a trace while the run is still writing it."""

    def __init__(self, sessions_dir: Path = SESSIONS_DIR):
        self.sessions_dir = sessions_dir

    def emit(self, run_id: str, event: dict) -> None:
        self._append_line(f"{run_id}.jsonl", event)

    def _append_line(self, filename: str, obj: dict) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / filename
        with open(path, "a") as f:
            f.write(json.dumps(obj, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


class StdoutSink(EventSink):
    """One compact JSON line per event/message, printed live as the run
    happens — hello_agent.py's own technique for watching a loop instead
    of waiting for it to return."""

    def emit(self, run_id: str, event: dict) -> None:
        print(json.dumps(event, default=str))


class MultiSink(EventSink):
    """Fans one event/message out to several sinks — e.g. persist to disk
    AND print live."""

    def __init__(self, *sinks: EventSink):
        self.sinks = sinks

    def emit(self, run_id: str, event: dict) -> None:
        for sink in self.sinks:
            sink.emit(run_id, event)
