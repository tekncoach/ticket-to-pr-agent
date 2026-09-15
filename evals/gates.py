# evals/gates.py
#
# The decision rule. Metrics say what happened; this says whether it ships.
#
# Two rules, and they are the same rule twice:
#
#   A threshold reads the LOWER BOUND of a range, never the median. The same
#   case in this suite has scored 0.00 and 1.00 on consecutive passes, so a
#   median is a draw quoted as a promise.
#
#   A threshold whose metric could not be measured is SKIPPED and reported as
#   skipped. Never passed. A gate that reports green for checks it never ran is
#   worse than no gate, because someone believes it.
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

GATES_PATH = Path(__file__).parent / "gates.yaml"

Status = str  # "pass" | "fail" | "skip"


@dataclass(frozen=True)
class GateResult:
    name: str
    status: Status
    threshold: Any = None
    observed: Any = None
    why: str = ""

    def __str__(self) -> str:
        mark = {"pass": "ok  ", "fail": "FAIL", "skip": "----"}[self.status]
        detail = f" ({self.why})" if self.why else ""
        return (f"{mark} {self.name:<22} "
                f"observed={self.observed} threshold={self.threshold}{detail}")


def load_gates(path: Path = GATES_PATH, tier: str | None = None) -> dict:
    """Thresholds, with a tier's overrides folded in.

    A tier block narrows, never widens by accident: the override simply wins,
    and gates.yaml documents why the deterministic tier is held higher.
    """
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overrides = (config.pop("tiers", None) or {}).get(tier or "", {})
    return {**config, **overrides}


def _lower_bound(metric: Any) -> float | None:
    """A spread's floor, or a bare number, or None. Never the median."""
    if metric is None:
        return None
    if isinstance(metric, dict):
        return metric.get("min")
    return float(metric)


def _upper_bound(metric: Any) -> float | None:
    if metric is None:
        return None
    if isinstance(metric, dict):
        return metric.get("max")
    return float(metric)


def check_gates(metrics: dict, gates: dict) -> tuple[bool, list[GateResult]]:
    """(ok, results). ok is false only on a real breach — never on a skip."""
    results: list[GateResult] = []

    def minimum(name: str, metric_key: str, worst=_lower_bound, why_missing=""):
        threshold = gates.get(name)
        observed = worst(metrics.get(metric_key))
        if threshold is None:
            results.append(GateResult(name, "skip", why=why_missing or "disabled"))
        elif observed is None:
            results.append(GateResult(name, "skip", threshold,
                                      why="not measured in this run"))
        else:
            results.append(GateResult(
                name, "pass" if observed >= threshold else "fail", threshold, observed))

    def maximum(name: str, metric_key: str, why_missing=""):
        threshold = gates.get(name)
        observed = _upper_bound(metrics.get(metric_key))
        if threshold is None:
            results.append(GateResult(name, "skip", why=why_missing or "disabled"))
        elif observed is None:
            results.append(GateResult(name, "skip", threshold,
                                      why="not measured in this run"))
        else:
            results.append(GateResult(
                name, "pass" if observed <= threshold else "fail", threshold, observed))

    minimum("min_pass_rate", "pass_at_1")
    minimum("min_p0_pass_rate", "p0_pass_rate",
            why_missing="no P0 case in this scope")
    minimum("min_mean_faithfulness", "mean_faithfulness",
            why_missing="the judge is not trusted to block — JUDGE-CALIBRATION.md")
    maximum("max_p95_latency_ms", "p95_latency_ms")
    maximum("max_cost_usd_per_case", "cost_usd_per_case",
            why_missing="no token price configured")

    # Behaviours that fail the build outright. Only the deterministically
    # detected ones are listed; a gate naming a behaviour nothing emits cannot
    # fire, and one that cannot fire is decoration.
    forbidden = gates.get("forbidden_behaviors") or []
    seen = metrics.get("violations") or {}
    breached = {b: seen[b] for b in forbidden if b in seen}
    if not forbidden:
        results.append(GateResult("forbidden_behaviors", "skip", why="none listed"))
    else:
        results.append(GateResult(
            "forbidden_behaviors", "fail" if breached else "pass",
            threshold="none", observed=breached or "none",
            why=", ".join(f"{k} x{v}" for k, v in breached.items())))

    return not any(r.status == "fail" for r in results), results
