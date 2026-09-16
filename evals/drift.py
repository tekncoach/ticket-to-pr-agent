# evals/drift.py
#
# Comparing one run to a baseline, and refusing to call noise a change.
#
# The template's compare() reads metrics["pass_rate"] and alerts on a 3-point
# drop. This repo does not have a flat pass_rate on purpose: the same case has
# scored 0.00 and 1.00 on consecutive passes, and a threshold set at the
# observed floor broke on the next draw with nothing changed. So a comparison
# between two point estimates cannot tell drift from a draw, and a monitor that
# fires on a draw is switched off inside a week.
#
# What is compared instead:
#
#   ranges       a drop counts only when the latest MAX falls below the
#                baseline MIN — the two do not overlap, so no single draw
#                explains it.
#   composition  a failure mode that appears where there was none, or a case
#                that flipped from pass to fail, regardless of the aggregate.
#                The rates can hold perfectly still while the set of things
#                failing turns over completely.
#   environment  model, corpus and golden-set hash. A drop that coincides with
#                a corpus change is not the same finding as one that does not,
#                and reporting the delta without the environment invites the
#                wrong fix.
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

# A drop this size is reported even when the ranges still overlap — not as
# drift, as something to look at. Below it, two overlapping ranges are silence.
WATCH_DELTA = 0.05


def _range(metric) -> tuple[float, float] | None:
    if metric is None:
        return None
    if isinstance(metric, dict):
        lo, hi = metric.get("min"), metric.get("max")
        return (lo, hi) if lo is not None and hi is not None else None
    return (float(metric), float(metric))


def _rate_alerts(name: str, base, late) -> list[str]:
    b, l = _range(base), _range(late)
    if b is None or l is None:
        # Not measured on one side is not a drop. It is a gap, and it is said.
        return [f"note  {name}: not comparable ({base} vs {late})"]
    if l[1] < b[0]:
        return [f"DRIFT {name}: {b[0]:.3f}-{b[1]:.3f} -> {l[0]:.3f}-{l[1]:.3f} "
                f"(ranges do not overlap)"]
    if l[0] < b[0] - WATCH_DELTA:
        return [f"watch {name}: floor {b[0]:.3f} -> {l[0]:.3f}, ranges still overlap"]
    return []


def _scope(report: dict) -> str:
    return ",".join((report.get("scope") or {}).get("tier") or ["mixed"])


def compare(baseline: dict, latest: dict) -> list[str]:
    """Alerts, loudest first. Empty means nothing moved that a draw explains."""
    alerts: list[str] = []

    # A retrieval run and a model run are not the same measurement, and
    # subtracting one from the other manufactures a delta out of a change of
    # subject. Refused rather than reported, because the numbers it would
    # produce look exactly like real ones.
    if _scope(baseline) != _scope(latest):
        return [f"DRIFT incomparable: baseline is {_scope(baseline)}, "
                f"latest is {_scope(latest)} — compare like with like"]
    b, l = baseline.get("metrics", {}), latest.get("metrics", {})

    for name in ("pass_at_1", "p0_pass_rate", "grounded_rate", "mean_faithfulness"):
        alerts += _rate_alerts(name, b.get(name), l.get(name))

    # A ceiling, so the comparison inverts: the worst pass is what matters.
    base_latency, late_latency = _range(b.get("p95_latency_ms")), _range(l.get("p95_latency_ms"))
    if base_latency and late_latency and late_latency[1] > base_latency[1] * 2:
        alerts.append(f"DRIFT p95_latency_ms: {base_latency[1]:.0f} -> {late_latency[1]:.0f} (doubled)")

    # Composition. A mode appearing where there was none is drift even when
    # every rate holds, because the aggregate cannot distinguish one failure
    # replacing another from nothing having changed.
    before, after = b.get("violations") or {}, l.get("violations") or {}
    for mode in sorted(set(after) - set(before)):
        alerts.append(f"DRIFT new failure mode: {mode} x{after[mode]}")
    for mode in sorted(set(before) - set(after)):
        alerts.append(f"note  failure mode gone: {mode}")

    flipped = _flips(baseline, latest)
    if flipped["to_fail"]:
        alerts.append(f"DRIFT newly failing: {', '.join(sorted(flipped['to_fail']))}")
    if flipped["to_pass"]:
        alerts.append(f"note  newly passing: {', '.join(sorted(flipped['to_pass']))}")

    alerts += _environment(baseline, latest)
    return sorted(alerts, key=lambda a: (not a.startswith("DRIFT"), a))


def _flips(baseline: dict, latest: dict) -> dict[str, set]:
    """Cases that changed verdict. The aggregate can hold perfectly still
    while the set of things failing turns over completely."""
    def verdicts(report):
        return {c["id"]: c["pass"] for c in (report.get("cases") or report.get("scores") or [])}

    before, after = verdicts(baseline), verdicts(latest)
    shared = set(before) & set(after)
    return {
        "to_fail": {c for c in shared if before[c] and not after[c]},
        "to_pass": {c for c in shared if not before[c] and after[c]},
    }


def _environment(baseline: dict, latest: dict) -> list[str]:
    """What changed underneath. A drop that coincides with a new corpus is a
    different finding from one that does not, and the fix differs with it."""
    alerts = []
    for field, label in (("model", "model"), ("golden_sha256", "golden set"),
                         ("corpus_sha256", "corpus"), ("agent_sha", "agent commit")):
        before, after = baseline.get(field), latest.get(field)
        if before and after and before != after:
            alerts.append(f"note  {label} changed: {str(before)[:12]} -> {str(after)[:12]}")
    return alerts


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a run to a baseline.")
    parser.add_argument("--baseline", type=Path, default=RESULTS / "baseline.json")
    parser.add_argument("--latest", type=Path, default=RESULTS / "latest.json")
    parser.add_argument("--allow-empty", action="store_true",
                        help="exit 0 when the latest run is missing (CI before "
                             "anything has been recorded)")
    parser.add_argument("--fail-on-drift", action="store_true")
    args = parser.parse_args()

    if not args.baseline.exists() or not args.latest.exists():
        missing = args.baseline if not args.baseline.exists() else args.latest
        print(f"nothing to compare: {missing} is not there")
        return 0 if args.allow_empty else 1

    alerts = compare(_load(args.baseline), _load(args.latest))
    for alert in alerts:
        print(f"  {alert}")
    drifted = [a for a in alerts if a.startswith("DRIFT")]
    print(f"\n{len(drifted)} drift, {len(alerts) - len(drifted)} notes"
          f"  ({args.baseline.name} -> {args.latest.name})")
    return 1 if (drifted and args.fail_on_drift) else 0


if __name__ == "__main__":
    raise SystemExit(main())
