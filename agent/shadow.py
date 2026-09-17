# agent/shadow.py
from dataclasses import dataclass
from typing import Any
import json, re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def redact(s: str) -> str:
    return EMAIL.sub("[EMAIL]", s)

@dataclass
class ShadowRecord:
    request_id: str
    input: str
    baseline: dict
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
