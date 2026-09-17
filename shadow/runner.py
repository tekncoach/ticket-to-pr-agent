# shadow/runner.py
#
# The shadow run: real input, live reads, every write a no-op that returns the
# payload it intended. One pairwise record per unit of traffic.
#
# Three things this file refuses to do, each because a drill names it:
#
#   It does not simulate reads. Only the consequence is removed, never the
#   evidence — a run against fixtures measures the fixtures.
#
#   It redacts at write time, not afterwards. Once a reporter's address is on
#   this disk it is on this disk, and every later step inherits that.
#
#   It does not treat its own SHADOW_MODE flag as proof that nothing was
#   written. shadow/audit.py asks the integration instead, because our flag and
#   our receipts are exactly what a bug in this file would have falsified.
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from agent.secrets_redaction import redact_secrets

HERE = Path(__file__).parent

# Redaction beyond secrets: an issue body is written by a member of the public.
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Greedy on the prefix: an earlier version matched from the third group on and
# left "+33 6 " sitting in the log, which is most of what identifies a number.
PHONE = re.compile(
    r"(?<![\w.])\+?\d[\d .()-]{7,17}\d(?![\w.])")
HANDLE = re.compile(r"(?<![\w/])@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")


def redact_deep(value):
    """Redact the strings inside a structure, never the structure itself.

    The first version redacted the serialised JSON, and the phone pattern ate
    the punctuation between fields — `"latency_ms": 1234.5, "x": 12` is a
    plausible phone number once the quotes stop mattering. It produced records
    that would not parse. Redaction belongs on values, where the shape is not
    part of what is being rewritten.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    return value


def redact(text: str) -> str:
    """Secrets, then the personal data a public issue carries.

    The project's own redactor first — it is what ships and what the eval
    suite checks — then the three patterns an issue tracker adds: addresses,
    phone numbers, and the handles that make a complaint attributable.
    """
    if not text:
        return text
    text = redact_secrets(text)
    text = EMAIL.sub("[EMAIL]", text)
    text = PHONE.sub("[PHONE]", text)
    return HANDLE.sub("[HANDLE]", text)


@dataclass
class ShadowRecord:
    request_id: str
    input: str
    baseline: dict
    agent_proposal: dict
    agent_trace: list
    would_write: list
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    error: str | None = None


def _proposal(outcome: dict, intended: list[dict]) -> dict:
    """What the agent would have done, in the terms the baseline is in.

    A proposal, not a result: the comparison is between two intentions, and
    calling ours a result would be the claim the day exists to avoid.
    """
    return {
        "answer": outcome.get("answer") or "",
        "writes_intended": len(intended),
        "tools_used": sorted({e["gen_ai.tool.name"] for e in outcome.get("trace", [])
                              if e.get("event") == "tool_call"}),
        "stopped_on": outcome.get("error"),
    }


def run_unit(unit: dict, model: str | None = None) -> ShadowRecord:
    from agent.factory import build_runtime

    intended: list[dict] = []
    runtime = build_runtime(model=model)
    # Reads stay live. Writes are refused by the runtime's own gate, which is
    # the guard that ships — not a switch this file invents for the occasion.
    runtime.allow_side_effects = lambda: False

    prompt = (f"Work this issue from {unit['repo']}.\n\n"
              f"#{unit['issue']} — {unit['title']}\n\n{unit['body']}")
    started = time.time()
    try:
        outcome = runtime.run(redact(prompt))
        error = outcome.get("error")
    except Exception as exc:  # noqa: BLE001 — one unit failing must not end a batch
        outcome, error = {"answer": "", "trace": []}, f"{type(exc).__name__}: {exc}"
    elapsed = (time.time() - started) * 1000

    usage = [e for e in outcome.get("trace", []) if e.get("event") == "llm_call"]
    trace = [e for e in outcome.get("trace", []) if e.get("event") != "message"]
    return ShadowRecord(
        request_id=unit["request_id"],
        input=redact(f"{unit['title']}\n\n{unit['body']}")[:4000],
        baseline=unit["baseline"],
        agent_proposal=redact_deep(_proposal(outcome, intended)),
        agent_trace=redact_deep(json.loads(json.dumps(trace, default=str))),
        would_write=intended,
        latency_ms=round(elapsed, 1),
        input_tokens=sum(e.get("gen_ai.usage.input_tokens") or 0 for e in usage),
        output_tokens=sum(e.get("gen_ai.usage.output_tokens") or 0 for e in usage),
        cached_tokens=sum(e.get("gen_ai.usage.cache_read.input_tokens") or 0 for e in usage),
        error=error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run traffic through the agent, writing nothing.")
    parser.add_argument("--traffic", type=Path, default=HERE / "traffic.jsonl")
    parser.add_argument("--limit", type=int, default=3,
                        help="units to run; the batch is deliberately small, see shadow/README.md")
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", type=Path, default=HERE / "results.jsonl")
    args = parser.parse_args()

    units = [json.loads(l) for l in args.traffic.read_text(encoding="utf-8").splitlines() if l.strip()]
    units = units[:args.limit]

    records = []
    for i, unit in enumerate(units, 1):
        print(f"  {i}/{len(units)}  {unit['request_id']}", flush=True)
        records.append(run_unit(unit, args.model))

    # Redacted already, at build time. Written once, here.
    args.out.write_text(
        "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8")
    fresh = sum(r.input_tokens for r in records)
    cached = sum(r.cached_tokens for r in records)
    print(f"\n{len(records)} pairwise records -> {args.out}")
    print(f"input tokens: {fresh} fresh, {cached} from cache")
    print("zero writes is not proven here — run `make shadow-audit`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
