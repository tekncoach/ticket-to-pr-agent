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


def _scored(report: dict) -> list[dict]:
    """Per-case rows, under either key. The report gained metrics and renamed
    "scores" to "cases"; old runs are still evidence and still readable."""
    return report.get("cases") or report.get("scores") or []


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
        failed = {s["id"] for s in _scored(report) if not s["pass"]}
        missing = {c for c in failed if (stamp, c) not in triaged}
        assert not missing, f"{stamp}: failures with no row in the sheet: {missing}"


def test_it_does_not_classify_cases_that_passed():
    for row in _golden_rows():
        report = json.loads((RESULTS / f"{row['pass_run']}.json").read_text(encoding="utf-8"))
        passed = {s["id"] for s in _scored(report) if s["pass"]}
        assert row["case_id"] not in passed, (
            f"{row['case_id']} passed in {row['pass_run']} but carries a failure mode"
        )


# --- the promotion path -----------------------------------------------------

def test_the_sheet_says_nothing_it_cannot_prove():
    # Every closed mode names a test that exists, every mode names a real case,
    # and nothing is closed with nothing pinning it. Three modes had sat here
    # marked FIXED with no proof, and two more had been triaged once and never
    # fixed at all — F4 matched a string the wire never sends, so it had never
    # fired, including on a real bypass.
    from evals.promote import check, load_sheet

    assert check(load_sheet()) == []


def test_a_mode_closed_without_a_pin_is_refused():
    from evals.promote import check

    rows = [{"mode": "FX", "case_id": "ref-001", "layer": "scorer",
             "severity": "P1", "status": "closed", "pinned_by": ""}]
    assert any("nothing pinning it" in p for p in check(rows))


def test_a_pin_naming_a_test_that_is_not_there_is_refused():
    from evals.promote import check

    rows = [{"mode": "FX", "case_id": "ref-001", "layer": "scorer",
             "severity": "P1", "status": "closed",
             "pinned_by": "tests/test_golden_scorers.py::test_nothing_like_this"}]
    assert any("which is not there" in p for p in check(rows))


def test_an_open_mode_may_not_claim_a_pin():
    # A pin is what closing means. Claiming one while open is the ambiguity
    # that let three modes read as fixed for a day.
    from evals.promote import check

    rows = [{"mode": "FX", "case_id": "ref-001", "layer": "scorer",
             "severity": "P1", "status": "open",
             "pinned_by": "tests/test_golden_scorers.py::test_a_clean_run_passes_and_says_what_the_judge_still_owes"}]
    assert any("claims a pin" in p for p in check(rows))


def test_triage_finds_a_failure_the_sheet_does_not_cover(tmp_path):
    # The promotion step: a failure nobody wrote down is indistinguishable from
    # one nobody noticed.
    from evals.promote import triage

    report = tmp_path / "r.json"
    report.write_text(json.dumps({"run_at": "X", "cases": [
        {"id": "qa-001", "pass": False, "severity": "P1", "violated": ["skip_citation"]},
        {"id": "qa-002", "pass": True, "severity": "P1", "violated": []},
    ]}), encoding="utf-8")
    candidates = triage([{"case_id": "ref-001"}], report)
    assert len(candidates) == 1 and "qa-001" in candidates[0]
    assert "skip_citation" in candidates[0]


def test_triage_stays_quiet_when_every_failure_is_already_tracked(tmp_path):
    from evals.promote import triage

    report = tmp_path / "r.json"
    report.write_text(json.dumps({"run_at": "X", "cases": [
        {"id": "qa-001", "pass": False, "severity": "P1", "violated": []}]}), encoding="utf-8")
    assert triage([{"case_id": "qa-001"}], report) == []
