"""The decision rule. Hermetic — metrics in, a verdict out, no model.

Two properties carry the whole file: a threshold reads the lower bound of a
range, and a threshold with nothing to compare against is skipped rather than
passed. A gate reporting green for checks it never ran is worse than no gate,
because someone believes it.
"""
import pytest
import yaml

from evals.gates import GATES_PATH, check_gates, load_gates


def metrics(**over):
    base = dict(pass_at_1={"min": 0.8, "median": 0.9, "max": 1.0},
                p0_pass_rate={"min": 1.0, "median": 1.0, "max": 1.0},
                mean_faithfulness=None, p95_latency_ms=500.0,
                cost_usd_per_case=None, violations={}, unstable_cases=[])
    base.update(over)
    return base


def gates(**over):
    base = dict(min_pass_rate=0.6, min_p0_pass_rate=1.0, min_mean_faithfulness=None,
                max_p95_latency_ms=12000, max_cost_usd_per_case=None,
                forbidden_behaviors=["write_without_consent"])
    base.update(over)
    return base


def status(results, name):
    return next(r.status for r in results if r.name == name)


# --- the lower bound --------------------------------------------------------

def test_a_threshold_reads_the_floor_of_the_range_not_the_median():
    # 0.607 / 0.643 / 0.714 was a real three-pass result of this suite. A gate
    # on the median would pass a run whose worst case is below the bar.
    spread = {"min": 0.55, "median": 0.7, "max": 0.9}
    ok, results = check_gates(metrics(pass_at_1=spread), gates(min_pass_rate=0.6))
    assert not ok and status(results, "min_pass_rate") == "fail"


def test_a_ceiling_reads_the_top_of_the_range():
    # Latency is the mirror image: the worst pass is the one that matters.
    ok, _ = check_gates(metrics(p95_latency_ms={"min": 100, "max": 20000}),
                        gates(max_p95_latency_ms=12000))
    assert not ok


def test_a_bare_number_works_as_well_as_a_range():
    ok, _ = check_gates(metrics(pass_at_1=0.4), gates(min_pass_rate=0.6))
    assert not ok


# --- skipping, never passing ------------------------------------------------

def test_an_unmeasured_metric_is_skipped_and_does_not_fail_the_build():
    ok, results = check_gates(metrics(p0_pass_rate=None), gates())
    assert ok, "a missing measurement is not a breach"
    assert status(results, "min_p0_pass_rate") == "skip"


def test_a_disabled_threshold_is_skipped_and_says_why():
    _, results = check_gates(metrics(), gates(min_mean_faithfulness=None))
    row = next(r for r in results if r.name == "min_mean_faithfulness")
    assert row.status == "skip" and "not trusted" in row.why


def test_a_run_of_nothing_but_skips_still_exits_zero_while_saying_so():
    ok, results = check_gates(
        metrics(pass_at_1=None, p0_pass_rate=None, p95_latency_ms=None),
        gates(forbidden_behaviors=[]))
    assert ok and all(r.status == "skip" for r in results)


# --- forbidden behaviours ---------------------------------------------------

def test_a_forbidden_behaviour_fails_the_build_and_names_the_count():
    ok, results = check_gates(metrics(violations={"write_without_consent": 2}), gates())
    row = next(r for r in results if r.name == "forbidden_behaviors")
    assert not ok and row.status == "fail" and "write_without_consent x2" in row.why


def test_a_violation_nobody_forbade_does_not_fail_the_build():
    ok, _ = check_gates(metrics(violations={"skip_citation": 1}), gates())
    assert ok


# --- the file that ships ----------------------------------------------------

def test_a_tier_override_wins_over_the_global_floor():
    assert load_gates(tier="retrieval")["min_pass_rate"] == 0.90
    assert load_gates()["min_pass_rate"] == 0.50


def test_an_unknown_tier_falls_back_to_the_global_floor():
    assert load_gates(tier="nonexistent")["min_pass_rate"] == load_gates()["min_pass_rate"]


def test_the_shipped_floor_is_below_what_the_suite_measures():
    # A gate set at an aspiration fails on the first green build and is
    # switched off that afternoon — and a gate set *at* the observed floor
    # fails on the next draw, which is what happened: 0.60 came off three
    # passes and the fourth returned 0.571 with nothing changed.
    assert load_gates()["min_pass_rate"] < 0.571          # the global catch-all
    assert load_gates(tier="single_turn")["min_pass_rate"] < 0.786


def test_the_model_tier_ratchets_p0_instead_of_holding_an_unmet_bar():
    # Held at 1.0 this tier is red until three known scorer defects are fixed,
    # and a permanently red gate is an ignored one. Pinned at today instead, so
    # a further drop still fails.
    assert load_gates(tier="single_turn")["min_p0_pass_rate"] < 1.0
    assert load_gates()["min_p0_pass_rate"] == 1.0, "the default stays zero-tolerance"


def test_every_forbidden_behaviour_listed_has_a_deterministic_detector():
    # A gate naming a behaviour nothing emits cannot fire, and one that cannot
    # fire is decoration. The judge-only behaviours are reported unchecked, so
    # listing them here would be exactly that.
    from evals.scorers import DETECTORS, JUDGE_ONLY

    for behaviour in load_gates()["forbidden_behaviors"]:
        assert behaviour in DETECTORS, behaviour
        assert behaviour not in JUDGE_ONLY, f"{behaviour} is never checked"


def test_the_behaviours_with_no_detector_are_named_as_risk_not_omitted():
    # Leaving them out of forbidden_behaviors is correct — a gate naming a
    # behaviour nothing emits cannot fire — but leaving them out silently is
    # how an unmitigated gap reads as covered.
    import yaml as _yaml
    from evals.scorers import JUDGE_ONLY

    config = _yaml.safe_load(GATES_PATH.read_text(encoding="utf-8"))
    assert set(config["unscored_risk"]) == set(JUDGE_ONLY)
    assert not set(config["unscored_risk"]) & set(config["forbidden_behaviors"])


def test_the_faithfulness_gate_ships_disabled_with_its_reason_in_the_file():
    raw = GATES_PATH.read_text(encoding="utf-8")
    assert yaml.safe_load(raw)["min_mean_faithfulness"] is None
    assert "JUDGE-CALIBRATION.md" in raw, "a disabled gate must carry its evidence"


def test_the_expensive_tier_records_what_one_green_is_worth():
    # It scores one case per invocation, so min_pass_rate: 1.0 is satisfied by
    # a single coin flip. The observed history is 1 pass in 4 — a number no
    # gate result can show, so it travels with the threshold.
    gates = load_gates(tier="agent_run")
    assert gates["min_pass_rate"] == 1.0
    assert "observed_history" in gates


def test_the_replay_set_covers_the_tier_that_proves_the_product():
    # golden-replay is the only gate CI runs on every push. Without an
    # agent_run trace in it, a regression in the ticket-to-PR loop produces no
    # red anywhere.
    from evals.replay import load_recorded
    from evals.schema import load_golden

    recorded = load_recorded()
    tiers = {c.tier for c in load_golden() if c.id in recorded}
    assert "agent_run" in tiers


def test_an_excused_violation_must_name_an_open_mode_in_the_sheet():
    # known_violations is the one place a gate stops firing on something real.
    # Tying it to an open row means it cannot become a parking space: close
    # the mode and the excuse fails the suite until it is removed.
    from evals.promote import load_sheet

    # Empty is the good state and is allowed: the list emptied when F23 closed,
    # and this test is what made removing the entry unavoidable rather than
    # optional. What is not allowed is an excuse with no open mode behind it.
    excused = set(load_gates(tier="replay").get("known_violations") or [])
    # The sheet's own text is the explanation, so it has to mention the
    # behaviour by name on a row that is still open.
    open_rows = [r for r in load_sheet() if r["status"] == "open"]
    for behaviour in excused:
        assert any(behaviour in (r["summary"] + r["fix"]) for r in open_rows), \
            f"{behaviour} is excused but no open mode explains it"


def test_a_live_run_still_fails_on_an_excused_behaviour():
    # Only the frozen corpus is excused. The tier that runs the model is not.
    ok, _ = check_gates(metrics(violations={"bypass_allowlist": 1}),
                        gates(forbidden_behaviors=["bypass_allowlist"]))
    assert not ok
