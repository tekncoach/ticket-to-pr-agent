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
