# evals/replay.py
#
# The gate that can run in CI, and an honest account of what it catches.
#
# Running the agent needs a corpus and a target checkout that a stateless
# runner does not have. Scoring a run that already happened needs neither: the
# trace is the whole input, and the scorers are pure functions over it.
#
# So this replays committed traces through the current scorers and thresholds.
#
#   It catches   a scorer change that re-scores past behaviour differently, a
#                threshold edit, a golden case edited so its own recorded run
#                no longer satisfies it, a detector that stops firing.
#   It does NOT  catch an agent regression. Nothing here calls a model; the
#                recorded behaviour is frozen. A new agent defect is caught by
#                `make golden`, on a machine that has the data.
#
# Saying that out loud is the point. A replay gate presented as a behavioural
# gate is the decoration this file exists to stop being.
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from agent.factory import TOOLS
from evals.gates import check_gates, load_gates
from evals.metrics import case_facts, summarize
from evals.schema import content_hash, load_golden
from evals.scorers import score_case

TRACES_DIR = Path(__file__).parent / "traces"


def record(case_id: str, outcome: dict, golden_sha: str,
           directory: Path = TRACES_DIR) -> Path:
    """Freeze one run so it can be scored again without being re-run."""
    directory.mkdir(exist_ok=True)
    path = directory / f"{case_id}.json"
    path.write_text(json.dumps({
        "case_id": case_id,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "golden_sha256": golden_sha,
        "answer": outcome.get("answer") or "",
        "error": outcome.get("error"),
        "trace": outcome.get("trace") or [],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def from_session(path: Path) -> dict:
    """Rebuild a run's outcome from the JSONL the runtime already wrote.

    The expensive tier cannot be re-run on demand just to be recorded — the
    ticket it worked is finished, and a second run measures a different case.
    But its trace is on disk, complete, and is the same events run() returned.
    So a canonical run is recorded from what actually happened rather than
    from a fresh one staged to look like it.
    """
    events = [json.loads(line) for line in
              path.read_text(encoding="utf-8").splitlines() if line.strip()]
    answer = ""
    for event in events:
        if event.get("event") == "message" and event.get("role") == "assistant":
            blocks = event.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            if text:
                answer = text
    # The stream carries conversation alongside metrics; the scorers read the
    # structured half, which is what run() returns as "trace".
    trace = [e for e in events if e.get("event") != "message"]
    return {"answer": answer, "trace": trace}


def load_recorded(directory: Path = TRACES_DIR) -> dict[str, dict]:
    if not directory.exists():
        return {}
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(directory.glob("*.json"))}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-score committed traces. No model, no corpus, no secrets.")
    parser.add_argument("--no-gate", action="store_true")
    args = parser.parse_args()

    recorded = load_recorded()
    if not recorded:
        print("no recorded traces — run `make golden-record` on a machine with the corpus")
        return 0

    cases = {c.id: c for c in load_golden()}
    facts, orphans, stale = [], [], []
    for case_id, run in recorded.items():
        case = cases.get(case_id)
        if case is None:
            # A recording whose case was deleted or renamed. Reported, never
            # scored: it would otherwise vanish quietly along with its coverage.
            orphans.append(case_id)
            continue
        if run.get("golden_sha256") != content_hash():
            stale.append(case_id)
        outcome = {"answer": run["answer"], "trace": run["trace"], "error": run.get("error")}
        score = score_case(case, outcome, TOOLS)
        # Latency is not replayable — the number belongs to the machine that
        # ran it, not to this one. Zero here, and the latency gate skips.
        facts.append(case_facts(case, outcome, score, 0.0))
        print(f"  {'pass' if score.pass_ else 'FAIL'} {case_id:<12} "
              f"tools={score.tool_match:.2f} "
              f"{'violated=' + ','.join(score.violated) if score.violated else ''}")

    metrics = summarize([facts], 0.0)
    # Its own block: the recordings span tiers, so neither the deterministic
    # tier's high bar nor the global zero-tolerance P0 describes them.
    ok, results = check_gates(metrics, load_gates(tier="replay"))

    print()
    for result in results:
        print(result)
    if orphans:
        print(f"\norphaned recordings (case gone): {orphans}")
    if stale:
        print(f"\nrecorded against an older golden set: {len(stale)} of {len(recorded)}")
    print(f"\n{'REPLAY GATE PASS' if ok else 'REPLAY GATE FAIL'} "
          f"({len(facts)} recorded runs re-scored)")
    return 0 if (ok or args.no_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
