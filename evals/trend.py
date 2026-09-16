# evals/trend.py
#
# The series, not the pair.
#
# evals/drift.py compares a run to a baseline, which catches a step. It cannot
# catch a slide: five runs each a point lower than the last, every consecutive
# pair well inside the noise, and a tenth of the suite gone by the end. A
# refusal rate climbing over a week is the alarm you get before anyone
# complains, and it never shows up in a two-run diff.
#
# Production gives no labels, so the signals worth watching are the ones that
# move BEFORE quality does:
#
#   refusal_rate    climbing means the agent is declining work it used to do
#   tool_mix        the same answers arrived at differently, usually worse
#   grounded_rate   citations thinning out before anyone notices a wrong claim
#   pass_at_1       the lagging one, kept for context rather than for alarm
#
# Runs are grouped by scope, because a retrieval run and a model run are not
# points on one line. Comparing them would manufacture a trend out of a change
# of subject.
from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

SIGNALS = ("refusal_rate", "grounded_rate", "pass_at_1", "tool_precision")
# A slide has to be monotone across at least this many runs before it is worth
# a word. Below that, three points down is what this suite does at rest.
MIN_RUN = 3
# ...and it has to have gone somewhere, not just wobbled downhill.
MIN_TOTAL = 0.10
# Below that but still moving one way: printed, not alarmed. The first real
# history had tool_precision down five runs running for 0.085 total — a slide
# no pair comparison sees, sitting just under the bar. Lowering the bar until
# it fires is how a threshold stops meaning anything; saying it out loud at a
# lower volume is not.
WATCH_TOTAL = 0.05


def _point(metric) -> float | None:
    if metric is None:
        return None
    return metric.get("median") if isinstance(metric, dict) else float(metric)


def load_series(directory: Path = RESULTS) -> dict[str, list[dict]]:
    """Runs grouped by scope, oldest first."""
    series: dict[str, list[dict]] = {}
    for path in sorted(directory.glob("*.json")):
        if path.name in ("latest.json", "baseline.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        scope = report.get("scope") or {}
        tier = ",".join(scope.get("tier") or ["mixed"])
        series.setdefault(tier, []).append(report)
    return series


def slides(runs: list[dict]) -> list[str]:
    """Signals that have moved one way for MIN_RUN runs and gone far enough."""
    found = []
    for signal in SIGNALS:
        points = [(r["run_at"], _point(r.get("metrics", {}).get(signal))) for r in runs]
        values = [(stamp, v) for stamp, v in points if v is not None]
        if len(values) < MIN_RUN:
            continue
        # The longest run ending at the newest point, in either direction.
        for direction, word in ((-1, "falling"), (1, "climbing")):
            length, i = 1, len(values) - 1
            while i > 0 and (values[i][1] - values[i - 1][1]) * direction > 0:
                length += 1
                i -= 1
            span = abs(values[-1][1] - values[i][1])
            if length < MIN_RUN or span < WATCH_TOTAL:
                continue
            level = "" if span >= MIN_TOTAL else "watch "
            found.append(
                f"{level}{word:<8} {signal:<16} {values[i][1]:.3f} -> "
                f"{values[-1][1]:.3f} over {length} runs, since {values[i][0]}")
    return found


def mix_shift(runs: list[dict]) -> list[str]:
    """Tools whose share of calls has moved more than a tenth since the oldest
    run in the series. The agent reaching for a different tool is drift even
    when it arrives at the same answers."""
    if len(runs) < 2:
        return []
    first = runs[0].get("metrics", {}).get("tool_mix") or {}
    last = runs[-1].get("metrics", {}).get("tool_mix") or {}
    shifts = []
    for tool in sorted(set(first) | set(last)):
        before, after = first.get(tool, 0.0), last.get(tool, 0.0)
        if abs(after - before) >= 0.10:
            shifts.append(f"mix      {tool:<28} {before:.2f} -> {after:.2f}")
    return shifts


def main() -> int:
    parser = argparse.ArgumentParser(description="Signals over the run history.")
    parser.add_argument("--tier", default=None, help="only this scope")
    parser.add_argument("--fail-on-slide", action="store_true")
    args = parser.parse_args()

    series = load_series()
    if args.tier:
        series = {k: v for k, v in series.items() if k == args.tier}

    alerts = 0
    for tier, runs in sorted(series.items()):
        print(f"\n{tier}  ({len(runs)} runs, {runs[0]['run_at']} -> {runs[-1]['run_at']})")
        for signal in SIGNALS:
            values = [_point(r.get("metrics", {}).get(signal)) for r in runs]
            shown = " ".join("  ·  " if v is None else f"{v:.3f}" for v in values[-8:])
            print(f"  {signal:<16} {shown}")
        for line in slides(runs) + mix_shift(runs):
            print(f"  {'·' if line.startswith('watch') else '⚠'} {line}")
            alerts += not line.startswith("watch")

    print(f"\n{alerts} signal(s) moving"
          if alerts else "\nno signal has moved consistently")
    return 1 if (alerts and args.fail_on_slide) else 0


if __name__ == "__main__":
    raise SystemExit(main())
