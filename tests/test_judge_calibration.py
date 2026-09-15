"""The calibration protocol, without calling a judge.

What is worth testing here is the protocol, not the model: that labels cannot
silently be reused against a different answer, that the agreement arithmetic
is chance-corrected, and that the probes exist at all — a calibration with no
low end measures assent rather than detection.
"""
import json

import pytest

from evals.judge import LABELS_PATH, PROBES, SAMPLE_PATH, _agreement, _sha
from evals.schema import JUDGE

SAMPLES = [json.loads(l) for l in SAMPLE_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
LABELS = [json.loads(l) for l in LABELS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_every_sample_is_labelled_and_pinned_to_the_answer_that_was_read():
    # A label written against one answer says nothing about another, and this
    # agent answers differently between runs.
    by_id = {s["id"]: s for s in SAMPLES}
    assert {l["id"] for l in LABELS} == set(by_id)
    for label in LABELS:
        assert label["answer_sha"] == by_id[label["id"]]["answer_sha"], label["id"]


def test_the_digest_is_over_the_answer_itself():
    assert _sha("x") != _sha("y")
    assert SAMPLES[0]["answer_sha"] == _sha(SAMPLES[0]["answer"])


def test_the_sample_has_a_low_end():
    # Without planted failures a judge that answers 5 to everything agrees
    # with every label and looks perfect.
    scores = [l["score"] for l in LABELS]
    assert min(scores) <= 2, "nothing in the sample is supposed to be unfaithful"
    assert len([s for s in scores if s <= 2]) >= len(PROBES)


def test_every_probe_is_present_and_says_what_it_plants():
    ids = {s["id"] for s in SAMPLES}
    for probe_id, what, _expected, _corrupt in PROBES:
        assert probe_id in ids
        assert what


def test_no_empty_answer_reaches_the_judge():
    # Faithfulness is undefined on a non-answer: it asserts nothing, so the
    # rubric scores it 5, which would be a free pass for a run that said
    # nothing at all.
    assert all(s["answer"].strip() for s in SAMPLES)


def test_the_rubric_binds_the_score_to_the_claims_it_lists():
    # Measured: before this sentence the judge listed a fabricated citation
    # and scored the answer 4. A score and a list of violations that do not
    # constrain each other are two separate opinions.
    assert "at most 3" in JUDGE and "fabricated citation" in JUDGE


def test_perfect_agreement_is_one_and_opposite_judgement_is_negative():
    assert _agreement([(5, 5), (1, 1), (3, 3)])["exact"] == 1.0
    assert _agreement([(5, 5), (1, 1), (3, 3)])["quadratic_kappa"] == 1.0
    assert _agreement([(1, 5), (5, 1)])["quadratic_kappa"] < 0


def test_a_judge_that_always_says_five_scores_zero_agreement_not_high():
    # Raw agreement on a sample of mostly 5s flatters a constant judge; the
    # chance-corrected number is the one that survives being asked about it.
    pairs = [(5, 5)] * 20 + [(1, 5), (2, 5)]
    result = _agreement(pairs)
    assert result["exact"] > 0.9
    assert result["quadratic_kappa"] == pytest.approx(0.0, abs=1e-9)


def test_within_one_is_looser_than_exact():
    pairs = [(4, 5), (3, 4), (5, 5)]
    result = _agreement(pairs)
    assert result["within_one"] == 1.0 and result["exact"] < 1.0


# --- sampling the judge -----------------------------------------------------

def test_a_range_is_min_median_max_not_a_mean():
    # At five passes a standard deviation describes the estimator more than the
    # instrument; the range is what anyone actually quotes.
    from evals.judge import _spread

    assert _spread([0.65, 0.73, 0.67]) == {"min": 0.65, "median": 0.67, "max": 0.73}
    assert _spread([1.0, 2.0])["median"] == 1.5


def test_several_passes_report_a_range_and_name_what_would_not_settle(tmp_path, monkeypatch):
    # The point of sampling: an aggregate that hides a coin flip is worse than
    # no aggregate, so the unstable cases are named next to the range.
    from evals import judge

    swinging = iter([5, 1] * 200)
    monkeypatch.setattr(judge, "_judge_once",
                        lambda client, prompt: {"score": next(swinging),
                                                "unsupported": [], "rationale": ""})
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda **kw: object())
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    monkeypatch.setattr(judge, "REPORT_PATH", tmp_path / "report.json")

    assert judge.calibrate(passes=2) == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["passes"] == 2
    assert set(report["agreement"]["quadratic_kappa"]) == {"min", "median", "max"}
    assert report["unstable_cases"], "a judge alternating 5 and 1 must be reported unstable"


def test_a_single_pass_still_reports_a_point():
    # --passes defaults to 1, and a point estimate must not pretend to be a range.
    report = json.loads((SAMPLE_PATH.parent / "judge-calibration.json").read_text(encoding="utf-8"))
    if report.get("passes", 1) == 1:
        assert isinstance(report["agreement"]["quadratic_kappa"], float)
    else:
        assert set(report["agreement"]["quadratic_kappa"]) == {"min", "median", "max"}


def test_the_clamp_catches_the_probe_the_judge_never_does():
    # probe-citation was missed on all ten raw passes and caught on every
    # clamped one. This pins that it is the citation check doing it.
    from evals.judge import _fabricates_citation

    by_id = {s["id"]: s for s in SAMPLES}
    assert _fabricates_citation(by_id["probe-citation"])
    assert not _fabricates_citation(by_id["probe-figure"])


def test_the_reported_calibration_still_carries_the_clamped_detection():
    report = json.loads((SAMPLE_PATH.parent / "judge-calibration.json").read_text(encoding="utf-8"))
    detection = report["probe_detection"]
    assert "caught_clamped" in detection
    assert not detection.get("missed_every_pass_clamped", ["x"])
