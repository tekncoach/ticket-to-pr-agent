"""Suite metrics. Hermetic — literal facts in, numbers out.

The rule the whole module rests on: a number that cannot be computed is None,
never a zero and never a default. A gate reading 0.0 where the truth is
"nobody measured" blocks a release for a reason that does not exist.
"""
import pytest

from evals.metrics import case_facts, percentile, spread, summarize
from evals.schema import CaseScore, GoldenCase


def fact(id="c", severity="P1", passed=True, **over):
    base = dict(id=id, severity=severity, split="core", **{"pass": passed},
                tool_precision=1.0, tool_recall=1.0, citation_expected=False,
                citation_ok=True, faithfulness=None, latency_ms=100.0,
                input_tokens=0, output_tokens=0, tool_calls=1)
    base.update(over)
    return base


def test_a_scope_with_no_p0_case_reports_none_not_zero():
    # Measured on the retrieval tier, which holds no P0 case: a guarded
    # denominator produced 0.0, which reads as "every critical case failed".
    assert summarize([[fact(severity="P1")]], 1.0)["p0_pass_rate"] is None


def test_p0_is_scored_only_over_the_p0_cases():
    facts = [fact("a", "P0", True), fact("b", "P0", False), fact("c", "P1", False)]
    assert summarize([facts], 1.0)["p0_pass_rate"]["median"] == 0.5


def test_pass_at_one_is_a_range_across_passes():
    metrics = summarize([[fact(passed=True)], [fact(passed=False)]], 1.0)
    assert metrics["pass_at_1"] == {"min": 0.0, "median": 0.5, "max": 1.0}


def test_a_case_that_answers_differently_between_passes_is_named():
    metrics = summarize([[fact("flaky", passed=True)], [fact("flaky", passed=False)]], 1.0)
    assert metrics["unstable_cases"] == ["flaky"]


def test_a_stable_case_is_not_named():
    assert summarize([[fact("x")], [fact("x")]], 1.0)["unstable_cases"] == []


def test_grounded_rate_ignores_cases_that_claimed_no_source():
    facts = [fact("a", citation_expected=True, citation_ok=False),
             fact("b", citation_expected=True, citation_ok=True),
             fact("c", citation_expected=False, citation_ok=True)]
    assert summarize([facts], 1.0)["grounded_rate"] == 0.5


def test_grounded_rate_is_none_when_nothing_claimed_a_source():
    assert summarize([[fact(citation_expected=False)]], 1.0)["grounded_rate"] is None


def test_faithfulness_is_none_until_a_judge_has_run():
    assert summarize([[fact()]], 1.0)["mean_faithfulness"] is None


def test_cost_is_none_unless_a_price_is_configured(monkeypatch):
    # This repo does not hardcode a vendor price list: it goes stale silently,
    # and the staleness surfaces as a cost gate that stopped meaning anything.
    import evals.metrics as m

    monkeypatch.setattr(m, "PRICE_IN", None)
    monkeypatch.setattr(m, "PRICE_OUT", None)
    assert m.summarize([[fact(input_tokens=1000)]], 1.0)["cost_usd_per_case"] is None

    monkeypatch.setattr(m, "PRICE_IN", "1.0")
    monkeypatch.setattr(m, "PRICE_OUT", "5.0")
    facts = [fact(input_tokens=1_000_000, output_tokens=1_000_000)]
    assert m.summarize([facts], 1.0)["cost_usd_per_case"] == 6.0


def test_a_case_expecting_no_tool_does_not_claim_perfect_precision():
    # Calling nothing when nothing was expected is correct, but scoring it 1.0
    # would inflate the suite average with a non-event.
    case = GoldenCase(id="r", input="x", tier="single_turn", split="core",
                      origin="test", must_refuse=True, expected_tools=[])
    score = CaseScore(id="r", **{"pass": True}, tool_match=1.0, citation_ok=True)
    facts = case_facts(case, {"answer": "no", "trace": []}, score, 10.0)
    assert facts["tool_precision"] is None and facts["tool_recall"] is None


def test_tokens_are_read_off_the_llm_calls_in_the_trace():
    case = GoldenCase(id="t", input="x", tier="single_turn", split="core",
                      origin="test", expected_tools=["bash"])
    score = CaseScore(id="t", **{"pass": True}, tool_match=1.0, citation_ok=True)
    trace = [{"event": "llm_call", "gen_ai.usage.input_tokens": 120,
              "gen_ai.usage.output_tokens": 30},
             {"event": "llm_call", "gen_ai.usage.input_tokens": 200,
              "gen_ai.usage.output_tokens": 40}]
    facts = case_facts(case, {"answer": "", "trace": trace}, score, 10.0)
    assert facts["input_tokens"] == 320 and facts["output_tokens"] == 70


def test_percentile_is_nearest_rank_and_empty_is_none():
    # At this sample size an interpolated percentile invents precision.
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.95) == 10
    assert percentile([], 0.95) is None


def test_spread_of_nothing_is_none():
    assert spread([]) is None
