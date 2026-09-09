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
    every sink below implements."""

    def emit(self, run_id: str, event: dict) -> None:
        pass


class NullSink(EventSink):
    """For tests: run() still calls emit() on every event, nothing is
    ever written anywhere."""


class JSONLFileSink(EventSink):
    """Appends to <sessions_dir>/<run_id>.jsonl. flush + fsync per line,
    not buffered — see runtime.py's emit() closure for why (a crash mid-run
    must not lose events from turns that already succeeded)."""

    def __init__(self, sessions_dir: Path = SESSIONS_DIR):
        self.sessions_dir = sessions_dir

    def emit(self, run_id: str, event: dict) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{run_id}.jsonl"
        with open(path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


class StdoutSink(EventSink):
    """One compact JSON line per event, printed live as the run happens —
    hello_agent.py's own technique for watching a loop instead of waiting
    for it to return."""

    def emit(self, run_id: str, event: dict) -> None:
        print(json.dumps(event, default=str))


class MultiSink(EventSink):
    """Fans one event out to several sinks — e.g. persist to disk AND
    print live."""

    def __init__(self, *sinks: EventSink):
        self.sinks = sinks

    def emit(self, run_id: str, event: dict) -> None:
        for sink in self.sinks:
            sink.emit(run_id, event)
