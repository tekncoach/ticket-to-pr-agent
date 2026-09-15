# evals/metrics.py
#
# Turning scored runs into the numbers a gate can read.
#
# One rule runs through all of it: a number that cannot be computed is None and
# says so, never a zero and never a default. A gate reading 0.0 where the truth
# is "nobody measured" blocks a release for a reason that does not exist, and a
# gate reading a made-up price passes one for the same reason.
from __future__ import annotations

import os
from typing import Any

from evals.schema import CaseScore, GoldenCase

# Dollars per million tokens, from the environment because this repo has no
# business hardcoding a vendor's price list — it goes stale silently and the
# staleness shows up as a cost gate that stopped meaning anything. Unset means
# cost is reported as tokens only, and the cost gate is skipped rather than
# passed.
PRICE_IN = os.environ.get("PRICE_PER_MTOK_INPUT")
PRICE_OUT = os.environ.get("PRICE_PER_MTOK_OUTPUT")


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank. At 28 samples an interpolated percentile invents precision
    the sample does not have."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(q * len(ordered) + 0.5))))
    return round(ordered[rank - 1], 1)


def spread(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (ordered[middle] if len(ordered) % 2
              else (ordered[middle - 1] + ordered[middle]) / 2)
    return {"min": round(min(ordered), 3), "median": round(median, 3),
            "max": round(max(ordered), 3)}


def case_facts(case: GoldenCase, outcome: dict, score: CaseScore,
               wall_ms: float) -> dict:
    """What one scored case contributes to the suite numbers."""
    from evals.scorers import called_tools, tool_results

    called = set(called_tools(outcome))
    expected = set(case.expected_tools)
    hit = called & expected
    usage_in = usage_out = 0
    for event in outcome.get("trace", []):
        if event.get("event") == "llm_call":
            usage_in += event.get("gen_ai.usage.input_tokens") or 0
            usage_out += event.get("gen_ai.usage.output_tokens") or 0
    return {
        "id": case.id,
        "severity": case.severity,
        "split": case.split,
        "pass": score.pass_,
        # None, not 1.0, when there was nothing to be precise about: a case
        # expecting no tools would otherwise report perfect precision for
        # having called none, and inflate the suite average with a non-event.
        "tool_precision": (len(hit) / len(called)) if called and expected else None,
        "tool_recall": (len(hit) / len(expected)) if expected else None,
        "citation_expected": bool(case.expected_citations_contains),
        "citation_ok": score.citation_ok,
        "faithfulness": score.faithfulness,
        "latency_ms": round(wall_ms, 1),
        "input_tokens": usage_in,
        "output_tokens": usage_out,
        "tool_calls": len(tool_results(outcome)),
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _cost_usd(facts: list[dict]) -> float | None:
    if not (PRICE_IN and PRICE_OUT):
        return None
    total = sum(f["input_tokens"] for f in facts) * float(PRICE_IN) / 1e6
    total += sum(f["output_tokens"] for f in facts) * float(PRICE_OUT) / 1e6
    return round(total / len(facts), 4) if facts else None


def summarize(passes: list[list[dict]], elapsed_s: float) -> dict[str, Any]:
    """Suite metrics across one or more passes over the same cases.

    pass@1 is a spread, not a point. The same case has scored 0.00 and 1.00 on
    consecutive runs of this very suite, so a single number here is a draw
    quoted as a promise. A gate reads the lower bound.
    """
    flat = [fact for pass_ in passes for fact in pass_]
    rates = [sum(1 for f in p if f["pass"]) / len(p) for p in passes if p]
    p0 = [f for f in flat if f["severity"] == "P0"]
    grounded = [f for f in flat if f["citation_expected"]]
    faithfulness = [f["faithfulness"] for f in flat if f["faithfulness"] is not None]

    # Which cases answered differently between passes. The suite average can
    # hold still while individual cases flip, and it is the flipping that
    # decides whether a threshold is a promise or a coin toss.
    by_case: dict[str, set] = {}
    for pass_ in passes:
        for fact in pass_:
            by_case.setdefault(fact["id"], set()).add(fact["pass"])

    return {
        "passes": len(passes),
        "cases_per_pass": len(passes[0]) if passes else 0,
        "pass_at_1": spread(rates),
        # None when the scope holds no P0 case at all. Dividing by a guarded
        # denominator gave 0.0 here on the retrieval tier, which reads as
        # "every critical case failed" and would block every pull request
        # for a reason that does not exist. Found by running it, not by review.
        "p0_pass_rate": spread([
            sum(1 for f in p if f["severity"] == "P0" and f["pass"]) / p0_in_pass
            for p in passes
            if (p0_in_pass := sum(1 for f in p if f["severity"] == "P0"))
        ]) or None,
        "p0_cases": len(p0) // max(1, len(passes)),
        "tool_precision": _mean([f["tool_precision"] for f in flat
                                 if f["tool_precision"] is not None]),
        "tool_recall": _mean([f["tool_recall"] for f in flat
                              if f["tool_recall"] is not None]),
        # Among the cases that claimed a source, how many carried it through.
        "grounded_rate": (_mean([1.0 if f["citation_ok"] else 0.0 for f in grounded])
                          if grounded else None),
        # None until a judge has run against this suite — reported as unmeasured
        # rather than as a passing default.
        "mean_faithfulness": _mean(faithfulness),
        "p95_latency_ms": percentile([f["latency_ms"] for f in flat], 0.95),
        "mean_input_tokens": _mean([float(f["input_tokens"]) for f in flat]),
        "mean_output_tokens": _mean([float(f["output_tokens"]) for f in flat]),
        # None unless PRICE_PER_MTOK_INPUT/OUTPUT are set: this repo does not
        # hardcode a vendor price list that goes stale without telling anyone.
        "cost_usd_per_case": _cost_usd(flat),
        "unstable_cases": sorted(cid for cid, seen in by_case.items() if len(seen) > 1),
        "elapsed_s": round(elapsed_s, 1),
    }
