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
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent.factory import SYSTEM_PROMPT
from evals.gates import check_gates, load_gates
from evals.runner import run_suite
from evals.schema import content_hash, load_golden

# Overridable so a gate run does not dirty the working tree. The pre-push hook
# runs on every push, and writing a report into the repository each time left
# the tree modified immediately after every push — a loop that trains people to
# ignore git status.
def _agent_sha() -> str | None:
    """The commit the agent ran at. Without it a drop cannot be attributed to
    anything, and the first question after "it dropped" is "since what?"."""
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip()[:12]
    except Exception:  # noqa: BLE001 — a tarball has no git, and that is fine
        return None


def _corpus_sha() -> str | None:
    """The corpus the retriever read. A drop that coincides with a corpus
    change is a different finding from one that does not."""
    import hashlib

    path = Path(os.environ.get("VECTOR_DB_PATH", "data/kb/kb.sqlite3"))
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:12]


RESULTS_DIR = Path(os.environ.get("EVAL_RESULTS_DIR")
                   or Path(__file__).parent / "results")


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
    parser.add_argument("--gates", default=None,
                        help="name the thresholds block to apply (default: the "
                             "tier's own, when exactly one tier was named)")
    parser.add_argument("--record", action="store_true",
                        help="freeze each run into evals/traces/ so CI can "
                             "re-score it without a corpus or a key")
    parser.add_argument("--judge", action="store_true",
                        help="grade faithfulness too: one extra model call per "
                             "case, and the score is clamped by what the trace proved")
    args = parser.parse_args()

    cases = load_golden()
    if args.tier:
        cases = [c for c in cases if c.tier in args.tier]
    if args.split:
        cases = [c for c in cases if c.split in args.split]
    if args.id:
        cases = [c for c in cases if c.id in args.id]

    result = run_suite(cases, passes=args.passes, model=args.model, judge=args.judge,
                       record=args.record)
    metrics = result["metrics"]

    # Thresholds come from the tier when exactly one was named. A mixed scope
    # takes the global floor: applying the deterministic tier's higher bar to a
    # run containing model calls would fail it for being what it is.
    tier = args.gates or (args.tier[0] if args.tier and len(args.tier) == 1 else None)
    gates = load_gates(tier=tier)
    ok, gate_results = check_gates(metrics, gates)

    report = {
        "run_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "golden_sha256": content_hash(),
        "model": args.model or os.environ.get("LLM_MODEL", "claude-haiku-4-5"),
        # What the run stood on. A delta without these invites the wrong fix:
        # "the pass rate dropped" and "the pass rate dropped after the corpus
        # was rebuilt" are different findings with different repairs.
        "agent_sha": _agent_sha(),
        "corpus_sha256": _corpus_sha(),
        "prompt_sha256": hashlib.sha256(
            SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
        "scope": {"tier": args.tier, "split": args.split, "id": args.id,
                  "gates_tier": tier, "judged": args.judge},
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
    # A gate that cannot see its own flakiness gives false confidence exactly
    # where being wrong costs most. This tier scores one case per invocation,
    # so the pass rate it reports is a coin flip, not a rate.
    if ok and tier == "agent_run" and args.passes == 1:
        print(f"\n⚠ one pass, one case: this green is a draw, not a rate. "
              f"Recorded history {gates.get('observed_history', 'unrecorded')}.")
    print(f"\n{'GATE PASS' if ok else 'GATE FAIL'} -> {path}")

    return 0 if (ok or args.no_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
