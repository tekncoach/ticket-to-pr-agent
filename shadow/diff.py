# shadow/diff.py
#
# Turning the pairwise log into a verdict.
#
# Without this the shadow run is a very well-instrumented data collector: two
# fields sitting next to each other in results.jsonl and nobody reading them
# together. "What did the shadow run tell you" has to have an answer that is
# not "I have logs".
#
# THE PRIMARY METRIC is file-level agreement: of the files the merged pull
# request changed, how many did the agent also touch. It is deliberately
# narrow, and narrow in a direction that can be checked — finding the right
# place is necessary for a correct change and nowhere near sufficient, so the
# number is a floor on competence and never a claim of correctness. Comparing
# the edits themselves needs a judge, and this project does not trust its judge
# with anything it can decide deterministically.
#
# THE GUARDRAIL is the completion rate: how many units reached a stated
# proposal at all. A high agreement rate over three units that finished out of
# sixty that did not is a number that flatters itself, so both travel together
# and neither is reported alone.
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent

# Files every pull request touches that say nothing about where the work is.
NOISE = ("CHANGELOG.md", "CHANGES.md", "HISTORY.md")


# The adjudication queue. A "partial" verdict says the agent touched some of
# the files the merged pull request changed and not all of them, which is two
# very different findings wearing the same word: it found half the fix, or it
# touched an unrelated file that happens to overlap. Nothing deterministic
# separates those, so the metric refuses to guess — an unadjudicated partial
# does not count as agreement, and the summary reports how many are waiting so
# the number is never quoted as if it were settled.
ADJUDICATIONS = HERE / "adjudications.json"
CALLS = ("half-the-fix", "coincidental")


def load_adjudications(path: Path = ADJUDICATIONS) -> dict:
    if not path.exists():
        return {}
    return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items()
            if isinstance(v, dict) and v.get("call") in CALLS}


def adjudication_queue(rows: list[dict], existing: dict) -> dict:
    """Every partial, with what it hit and what it missed, and a blank call.

    Written rather than printed because the answer has to survive the next run
    — a judgement made once and lost is a judgement made every time.
    """
    queue = dict(existing)
    for row in rows:
        if row["verdict"] != "partial" or row["id"] in queue:
            continue
        queue[row["id"]] = {"call": None, "why": "",
                            "hit": row["hit"], "missed": row["missed"]}
    return queue


def repo_relative(path: str, repo_hint: str = "") -> str:
    """The agent works in absolute paths; the baseline is repo-relative.

    Trimmed to the first path component the two can share, so
    /repo/httpx/_client.py and httpx/_client.py compare as the same file
    instead of never matching.
    """
    cleaned = (path or "").replace("\\", "/").rstrip("/")
    for marker in ("/repo/", f"/{repo_hint}/" if repo_hint else "\0"):
        if marker in cleaned:
            return cleaned.split(marker, 1)[1]
    parts = [p for p in cleaned.split("/") if p]
    return "/".join(parts[-3:]) if len(parts) > 3 else cleaned.lstrip("/")


def classify(record: dict) -> dict:
    """One record's verdict, with the sets it was computed from."""
    baseline = record.get("baseline") or {}
    proposal = record.get("agent_proposal") or {}

    if baseline.get("source") == "none" or not baseline.get("files"):
        return {"id": record["request_id"], "verdict": "baseline-unavailable",
                "hit": [], "missed": [], "extra": []}

    hint = (record["request_id"].split("-")[1] if "-" in record["request_id"] else "")
    wanted = {f for f in baseline["files"] if not f.endswith(NOISE)}
    touched = {repo_relative(p, hint) for p in (proposal.get("files_touched") or [])}
    touched = {p for p in touched if p}

    hit = sorted(f for f in wanted if any(f == t or f.endswith("/" + t) or t.endswith("/" + f)
                                          for t in touched))
    missed = sorted(wanted - set(hit))
    extra = sorted(t for t in touched
                   if not any(t == f or f.endswith("/" + t) or t.endswith("/" + f)
                              for f in wanted))

    # A run the runtime stopped did not reach a proposal, whatever its answer
    # field holds — the stop sentence lives there, so checking for an empty
    # answer reported all three guard-killed units as finished and the
    # guardrail read 1.0. The guardrail existing and the guardrail working are
    # different claims.
    if proposal.get("stopped_on"):
        verdict = "incomplete"
    elif not wanted:
        verdict = "baseline-unavailable"
    elif hit and not missed:
        verdict = "agreed"
    elif hit:
        verdict = "partial"
    else:
        verdict = "disagreed"

    return {"id": record["request_id"], "verdict": verdict, "hit": hit,
            "missed": missed, "extra": extra,
            "stopped_on": proposal.get("stopped_on"),
            "baseline_action": baseline.get("action", "")}


def summarise(records: list[dict], adjudications: dict | None = None) -> dict:
    adjudications = adjudications or {}
    rows = [classify(r) for r in records]

    def counts_as_agreement(row):
        if row["verdict"] == "agreed":
            return True
        if row["verdict"] != "partial":
            return False
        # Conservative on purpose: a partial nobody has looked at is not
        # evidence the agent found the place, and rounding it up is exactly
        # how an unverified judgement gets baked into a headline number.
        return adjudications.get(row["id"], {}).get("call") == "half-the-fix"

    pending = [r["id"] for r in rows if r["verdict"] == "partial"
               and r["id"] not in adjudications]
    comparable = [r for r in rows if r["verdict"] not in ("baseline-unavailable",)]
    finished = [r for r in rows if r["verdict"] not in ("incomplete", "baseline-unavailable")]

    def share(predicate, of):
        return round(sum(1 for r in of if predicate(r)) / len(of), 3) if of else None

    latencies = [r.get("latency_ms") for r in records if r.get("latency_ms")]
    fresh = [r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in records]

    return {
        "units": len(records),
        # The primary metric. Reported over units that finished, because a
        # unit that never stated a proposal did not agree or disagree.
        "file_agreement": {
            "of_finished": share(counts_as_agreement, finished),
            "exact": share(lambda r: r["verdict"] == "agreed", finished),
            "finished": len(finished),
            # Named, never defaulted: a pending partial is a number that is
            # not yet readable, not a zero.
            "partials_awaiting_adjudication": pending,
        },
        # The guardrail. A high agreement rate over the few units that finished
        # is a number that flatters itself.
        "completion_rate": share(lambda r: r["verdict"] != "incomplete", comparable),
        "stopped_on": {reason: sum(1 for r in rows if r.get("stopped_on") == reason)
                       for reason in sorted({r.get("stopped_on") for r in rows if r.get("stopped_on")})},
        "latency_ms": {
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "tokens_per_unit": round(statistics.mean(fresh), 1) if fresh else None,
        # Cost stays None unless a price is configured, for the same reason the
        # eval metrics do: a hardcoded vendor price goes stale in silence.
        "cost_usd_per_unit": None,
        "disagreements": [r for r in rows
                          if r["verdict"] in ("disagreed", "partial", "incomplete")][:5],
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare shadow proposals to the baseline.")
    parser.add_argument("--results", type=Path, default=HERE / "results.jsonl")
    parser.add_argument("--out", type=Path, default=HERE / "summary.json")
    args = parser.parse_args()

    if not args.results.exists():
        print(f"no results at {args.results} — run `make shadow-run` first")
        return 1

    records = [json.loads(l) for l in args.results.read_text(encoding="utf-8").splitlines() if l.strip()]
    adjudications = load_adjudications()
    summary = summarise(records, adjudications)

    queue = adjudication_queue(summary["rows"], adjudications)
    if queue:
        ADJUDICATIONS.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    agreement = summary["file_agreement"]
    print(f"{summary['units']} units, {agreement['finished']} reached a proposal")
    print(f"  file agreement   {agreement['of_finished']}  (exact {agreement['exact']})")
    print(f"  completion rate  {summary['completion_rate']}   <- the guardrail")
    waiting = summary["file_agreement"]["partials_awaiting_adjudication"]
    if waiting:
        print(f"  {len(waiting)} partial(s) not counted as agreement until called "
              f"in {ADJUDICATIONS.name}: {', '.join(waiting)}")
    print(f"  latency          median {summary['latency_ms']['median']}ms, "
          f"max {summary['latency_ms']['max']}ms")
    for reason, count in summary["stopped_on"].items():
        print(f"  stopped on {reason}: {count}")
    print()
    for row in summary["disagreements"]:
        print(f"  {row['verdict']:<12} {row['id']:<22} hit={row['hit']} missed={row['missed']}")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
