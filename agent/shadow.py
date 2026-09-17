# agent/shadow.py
from dataclasses import dataclass
from typing import Any
import json, re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def redact(s: str) -> str:
    return EMAIL.sub("[EMAIL]", s)

@dataclass
class Baseline:
    """What the current system actually did, for the same input.

    The half of a pairwise record that is not ours, and the one the whole day
    turns on: without it a shadow run is just a run. Four fields, because a
    comparison needs all four to mean anything.

    `source` says where the answer came from, and it is load-bearing rather
    than descriptive — a baseline taken from our own agent on an earlier
    revision is a different claim from one a human wrote, and reading a number
    without knowing which is how a comparison flatters itself.

    `action` is what was done in one line. `artifact` is the evidence — a diff,
    a comment body, a URL — so a disagreement can be read rather than trusted.
    `at` is when, because a baseline drifts: the human answer to a ticket in
    August is not the answer the same team would give today.
    """
    source: str          # "human-commit" | "human-comment" | "agent-revision:<sha>" | "none"
    action: str
    artifact: str | None = None
    at: str | None = None

    @classmethod
    def unavailable(cls, why: str) -> "Baseline":
        """No baseline for this input, said out loud.

        Not an empty dict: a record whose baseline is silently blank reads as
        agreement with nothing, and averages into the comparison as though it
        were a measurement. Same rule as the eval metrics — a value that could
        not be computed is named, never defaulted.
        """
        return cls(source="none", action=why)


@dataclass
class ShadowRecord:
    request_id: str
    input: str
    baseline: Baseline
    agent_proposal: dict
    agent_trace: list
    would_write: bool
    latency_ms: float
    cost_usd: float | None = None

def wrap_write_tool(handler):
    def shadowed(args: dict):
        return ToolResult(True, data={
            "shadow": True,
            "intended_args": args,
            "note": "not executed",
        })
    return shadowed

def run_shadow_batch(cases: list[dict], agent, baseline_fn) -> list[ShadowRecord]:
    out = []
    for c in cases:
        base = baseline_fn(c)
        result = agent.run(c["input"], allow_side_effects=False)
        out.append(ShadowRecord(...))
    Path("shadow/results.jsonl").write_text(
        "\n".join(json.dumps(asdict(r)) for r in out)
    )
    return out
