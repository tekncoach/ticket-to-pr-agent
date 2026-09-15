# evals/run.py
#
# The one command: run the golden set, measure it, and decide.
#
# It exits non-zero on a gate breach, which is the whole point — a suite that
# reports and never blocks is a report, not a gate. What it will not do is exit
# non-zero because a metric was missing: a threshold with nothing to compare
# against is reported as skipped, and a run made entirely of skips still exits
# 0 while saying so on every line.
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from evals.gates import check_gates, load_gates
from evals.runner import run_suite
from evals.schema import content_hash, load_golden

RESULTS_DIR = Path(__file__).parent / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden set and gate on it.")
    parser.add_argument("--tier", action="append",
                        choices=["retrieval", "single_turn", "agent_run"])
    parser.add_argument("--split", action="append",
                        choices=["core", "hard", "adversarial"])
    parser.add_argument("--id", action="append", help="run only these case ids")
    parser.add_argument("--model", default=None)
    parser.add_argument("--passes", type=int, default=1,
                        help="run every case N times; thresholds read the lower bound")
    parser.add_argument("--no-gate", action="store_true",
                        help="measure and report, always exit 0")
    args = parser.parse_args()

    cases = load_golden()
    if args.tier:
        cases = [c for c in cases if c.tier in args.tier]
    if args.split:
        cases = [c for c in cases if c.split in args.split]
    if args.id:
        cases = [c for c in cases if c.id in args.id]

    result = run_suite(cases, passes=args.passes, model=args.model)
    metrics = result["metrics"]

    # Thresholds come from the tier when exactly one was named. A mixed scope
    # takes the global floor: applying the deterministic tier's higher bar to a
    # run containing model calls would fail it for being what it is.
    tier = args.tier[0] if args.tier and len(args.tier) == 1 else None
    gates = load_gates(tier=tier)
    ok, gate_results = check_gates(metrics, gates)

    report = {
        "run_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "golden_sha256": content_hash(),
        "model": args.model or os.environ.get("LLM_MODEL", "claude-haiku-4-5"),
        "scope": {"tier": args.tier, "split": args.split, "id": args.id,
                  "gates_tier": tier},
        "gate": {"pass": ok,
                 "results": [r.__dict__ for r in gate_results]},
        "metrics": metrics,
        "skipped": result["skipped"],
        "unrunnable": result["unrunnable"],
        "cases": result["cases"],
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    body = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    path = RESULTS_DIR / f"{report['run_at']}.json"
    path.write_text(body, encoding="utf-8")
    # A copy, not a symlink: CI artifact upload handles a file, and a dangling
    # symlink reads as a missing run rather than a stale one.
    (RESULTS_DIR / "latest.json").write_text(body, encoding="utf-8")

    print()
    for gate_result in gate_results:
        print(gate_result)
    if metrics["unstable_cases"]:
        print(f"\nunstable across passes: {metrics['unstable_cases']}")
    print(f"\n{'GATE PASS' if ok else 'GATE FAIL'} -> {path}")

    return 0 if (ok or args.no_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
