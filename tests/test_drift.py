"""Drift detection. Hermetic — two reports in, alerts out.

The property the whole file rests on: a comparison between two point estimates
cannot tell drift from a draw. The same case in this suite has scored 0.00 and
1.00 on consecutive passes, so a monitor that fires on that is switched off
inside a week, and one that ignores a real drop is decoration.
"""
from evals.drift import compare


def report(pass_at_1=None, violations=None, cases=None, **extra):
    metrics = {"pass_at_1": pass_at_1, "p0_pass_rate": None, "grounded_rate": None,
               "mean_faithfulness": None, "p95_latency_ms": None,
               "violations": violations or {}}
    return {"metrics": metrics, "cases": cases or [], **extra}


def drifts(alerts):
    return [a for a in alerts if a.startswith("DRIFT")]


# --- ranges, not points -----------------------------------------------------

def test_overlapping_ranges_are_silence_not_drift():
    # 0.607 / 0.643 / 0.714 then 0.571 was a real sequence here with nothing
    # changed. A point comparison calls that a 4-point drop.
    alerts = compare(report({"min": 0.607, "max": 0.714}),
                     report({"min": 0.571, "max": 0.700}))
    assert drifts(alerts) == []


def test_a_drop_clear_of_the_baseline_range_is_drift():
    alerts = compare(report({"min": 0.78, "max": 0.82}),
                     report({"min": 0.60, "max": 0.64}))
    assert any("ranges do not overlap" in a for a in drifts(alerts))


def test_a_floor_falling_while_ranges_still_overlap_is_watched_not_alarmed():
    alerts = compare(report({"min": 0.80, "max": 0.95}),
                     report({"min": 0.70, "max": 0.90}))
    assert drifts(alerts) == []
    assert any(a.startswith("watch") for a in alerts)


def test_a_metric_measured_on_one_side_only_is_a_gap_not_a_drop():
    alerts = compare(report({"min": 0.8, "max": 0.8}), report(None))
    assert drifts(alerts) == []
    assert any("not comparable" in a for a in alerts)


# --- composition ------------------------------------------------------------

def test_a_new_failure_mode_is_drift_even_when_every_rate_holds():
    alerts = compare(report({"min": 0.8, "max": 0.8}),
                     report({"min": 0.8, "max": 0.8}, violations={"leak_secret": 1}))
    assert any("new failure mode: leak_secret" in a for a in drifts(alerts))


def test_a_mode_disappearing_is_noted_and_not_alarmed():
    alerts = compare(report(violations={"skip_citation": 2}), report())
    assert drifts(alerts) == []
    assert any("failure mode gone" in a for a in alerts)


def test_the_same_rate_with_different_cases_failing_is_still_drift():
    # The aggregate can hold perfectly still while the set of things failing
    # turns over completely. That is the case a rate cannot see.
    before = report({"min": 0.5, "max": 0.5},
                    cases=[{"id": "a", "pass": True}, {"id": "b", "pass": False}])
    after = report({"min": 0.5, "max": 0.5},
                   cases=[{"id": "a", "pass": False}, {"id": "b", "pass": True}])
    alerts = compare(before, after)
    assert any("newly failing: a" in a for a in drifts(alerts))
    assert any("newly passing: b" in a for a in alerts)


def test_a_case_absent_from_one_side_is_not_a_flip():
    before = report(cases=[{"id": "a", "pass": True}])
    after = report(cases=[{"id": "b", "pass": False}])
    assert drifts(compare(before, after)) == []


# --- latency ----------------------------------------------------------------

def test_latency_inverts_and_only_a_doubling_counts():
    base = report(); base["metrics"]["p95_latency_ms"] = {"min": 100, "max": 5000}
    same = report(); same["metrics"]["p95_latency_ms"] = {"min": 100, "max": 7000}
    worse = report(); worse["metrics"]["p95_latency_ms"] = {"min": 100, "max": 12000}
    assert drifts(compare(base, same)) == []
    assert any("doubled" in a for a in drifts(compare(base, worse)))


# --- environment ------------------------------------------------------------

def test_what_changed_underneath_travels_with_the_delta():
    # A drop that coincides with a new corpus is a different finding from one
    # that does not, and the fix differs with it.
    alerts = compare(report(model="haiku", golden_sha256="aaa"),
                     report(model="sonnet", golden_sha256="bbb"))
    assert any("model changed" in a for a in alerts)
    assert any("golden set changed" in a for a in alerts)


def test_an_unchanged_environment_says_nothing():
    assert compare(report(model="haiku"), report(model="haiku")) == [
        a for a in compare(report(model="haiku"), report(model="haiku"))
        if "changed" not in a]


def test_two_identical_runs_produce_no_drift():
    r = report({"min": 0.8, "max": 0.9}, cases=[{"id": "a", "pass": True}])
    assert drifts(compare(r, r)) == []
