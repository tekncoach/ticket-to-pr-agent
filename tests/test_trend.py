"""Signals over a history. Hermetic — reports in, alerts out.

drift compares a pair and catches a step. This catches a slide: five runs each
a point lower than the last, every consecutive pair well inside the noise, and
a tenth of the suite gone by the end. The first real history had exactly that.
"""
import json

from evals.trend import load_series, mix_shift, slides


def run(stamp, tier="single_turn", **metrics):
    base = {"refusal_rate": None, "grounded_rate": None, "pass_at_1": None,
            "tool_precision": None, "tool_mix": {}}
    base.update(metrics)
    return {"run_at": stamp, "scope": {"tier": [tier]}, "metrics": base}


def test_a_monotone_slide_no_pair_comparison_would_see_is_caught():
    runs = [run(f"t{i}", pass_at_1={"median": v})
            for i, v in enumerate([0.90, 0.86, 0.82, 0.78, 0.74])]
    found = slides(runs)
    assert any("falling" in f and "pass_at_1" in f for f in found)
    assert any("over 5 runs" in f for f in found)


def test_a_wobble_is_not_a_slide():
    runs = [run(f"t{i}", pass_at_1={"median": v})
            for i, v in enumerate([0.80, 0.60, 0.85, 0.62, 0.81])]
    assert slides(runs) == []


def test_a_slide_too_small_to_alarm_is_printed_as_a_watch():
    # Measured: tool_precision fell on five consecutive runs for 0.085 total —
    # real, and under the bar. Lowering the bar until it fires is how a
    # threshold stops meaning anything.
    runs = [run(f"t{i}", tool_precision=v)
            for i, v in enumerate((0.795, 0.788, 0.780, 0.740, 0.710))]
    found = slides(runs)
    assert found and all(f.startswith("watch") for f in found)


def test_a_short_history_says_nothing():
    assert slides([run("t0", pass_at_1={"median": 0.9}),
                   run("t1", pass_at_1={"median": 0.5})]) == []


def test_a_climb_is_reported_too():
    # A refusal rate climbing is the alarm that arrives before anyone
    # complains, and it climbs rather than falls.
    runs = [run(f"t{i}", refusal_rate=v) for i, v in enumerate([0.10, 0.20, 0.35, 0.50])]
    assert any("climbing" in f and "refusal_rate" in f for f in slides(runs))


def test_a_signal_absent_from_older_runs_is_skipped_not_invented():
    runs = [run("t0"), run("t1"), run("t2", pass_at_1={"median": 0.5})]
    assert slides(runs) == []


def test_a_tool_mix_shifting_is_drift_even_with_every_rate_steady():
    before = run("t0", tool_mix={"bash": 0.70, "search_kb": 0.30})
    after = run("t1", tool_mix={"bash": 0.30, "search_kb": 0.70})
    shifts = mix_shift([before, after])
    assert any("bash" in s for s in shifts) and any("search_kb" in s for s in shifts)


def test_a_small_mix_change_is_not_reported():
    before = run("t0", tool_mix={"bash": 0.50, "search_kb": 0.50})
    after = run("t1", tool_mix={"bash": 0.55, "search_kb": 0.45})
    assert mix_shift([before, after]) == []


def test_runs_are_grouped_by_scope(tmp_path):
    # A retrieval run and a model run are not points on one line; comparing
    # them manufactures a trend out of a change of subject.
    for stamp, tier in (("a", "retrieval"), ("b", "single_turn"), ("c", "retrieval")):
        (tmp_path / f"{stamp}.json").write_text(json.dumps(run(stamp, tier)), encoding="utf-8")
    (tmp_path / "latest.json").write_text(json.dumps(run("z")), encoding="utf-8")
    series = load_series(tmp_path)
    assert set(series) == {"retrieval", "single_turn"}
    assert len(series["retrieval"]) == 2, "latest.json is a copy, not a run"
