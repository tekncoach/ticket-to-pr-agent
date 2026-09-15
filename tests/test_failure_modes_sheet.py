"""The triage sheet stays attached to the runs it describes.

A failure-mode sheet is only worth what its coverage is worth: one that has
drifted from the run it claims to triage reports a taxonomy for failures
nobody looked at. Both halves are checked here — no invented case ids, and no
failure left unclassified in the runs the sheet names.
"""
import csv
import json

from evals.schema import GOLDEN_PATH, load_golden

SHEET = GOLDEN_PATH.parent / "failure-modes.csv"
RESULTS = GOLDEN_PATH.parent / "results"

ROWS = list(csv.DictReader(SHEET.open(encoding="utf-8")))
LAYERS = {"agent", "scorer", "schema", "case", "retrieval", "variance", "harness", "judge"}


def _golden_rows():
    """Rows observed in a golden run. Findings from the judge calibration live
    in the same sheet but are not scored against a results file."""
    return [r for r in ROWS if (RESULTS / f"{r['pass_run']}.json").exists()]


def test_the_sheet_has_rows_and_every_column_is_filled():
    assert ROWS
    for row in ROWS:
        assert all(row[col] for col in
                   ("mode", "case_id", "layer", "severity", "pass_run", "summary", "fix")), row


def test_every_case_it_names_exists_in_the_golden_set_or_the_judge_sample():
    # Planted probes are not golden cases — they exist only to give the
    # calibration a low end — but a finding about one belongs in this sheet.
    from evals.judge import PROBES

    ids = {c.id for c in load_golden()} | {p[0] for p in PROBES}
    unknown = {r["case_id"] for r in ROWS} - ids
    assert not unknown, f"the sheet triages cases that do not exist: {unknown}"


def test_every_layer_is_a_declared_one():
    assert {r["layer"] for r in ROWS} <= LAYERS


def test_a_mode_id_means_one_thing():
    # Two different defects under one label is how a taxonomy stops counting.
    by_mode: dict[str, set[str]] = {}
    for row in ROWS:
        by_mode.setdefault(row["mode"], set()).add(row["fix"])
    ambiguous = {m: f for m, f in by_mode.items() if len(f) > 1}
    assert not ambiguous, f"one mode, several fixes: {ambiguous}"


def test_every_failure_in_the_runs_it_names_is_classified():
    triaged = {(r["pass_run"], r["case_id"]) for r in _golden_rows()}
    for stamp in {r["pass_run"] for r in _golden_rows()}:
        report = json.loads((RESULTS / f"{stamp}.json").read_text(encoding="utf-8"))
        failed = {s["id"] for s in report["scores"] if not s["pass"]}
        missing = {c for c in failed if (stamp, c) not in triaged}
        assert not missing, f"{stamp}: failures with no row in the sheet: {missing}"


def test_it_does_not_classify_cases_that_passed():
    for row in _golden_rows():
        report = json.loads((RESULTS / f"{row['pass_run']}.json").read_text(encoding="utf-8"))
        passed = {s["id"] for s in report["scores"] if s["pass"]}
        assert row["case_id"] not in passed, (
            f"{row['case_id']} passed in {row['pass_run']} but carries a failure mode"
        )
