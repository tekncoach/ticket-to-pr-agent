"""The golden set loads, and cannot be edited into something that measures less.

Hermetic: no model, no corpus, no network. The set itself is a source file and
gets the same treatment as one — a typo in a forbidden behaviour or a tool name
must fail loudly here, not score silently as a behaviour nobody implemented.
"""
import json

import pytest

from evals.schema import (
    ForbiddenBehavior, GoldenCase, ToolName,
    GOLDEN_PATH, content_hash, load_golden, split_counts,
)

LOCK_PATH = GOLDEN_PATH.parent / "golden.lock.json"
CASES = load_golden()


def _mutate(index: int = 0, **changes) -> dict:
    row = json.loads(CASES[index].model_dump_json(by_alias=True, exclude_none=True))
    row.update(changes)
    return row


def test_every_case_loads():
    assert len(CASES) == 52


def test_the_set_is_the_size_the_brief_asks_for():
    assert 40 <= len(CASES) <= 60


def test_the_split_is_seventy_twenty_ten_within_a_case_or_two():
    counts = split_counts(CASES)
    total = len(CASES)
    for name, target in (("core", 0.70), ("hard", 0.20), ("adversarial", 0.10)):
        share = counts[name] / total
        assert abs(share - target) < 0.05, f"{name} is {share:.0%}, target {target:.0%}"


def test_every_expected_tool_is_a_tool_the_agent_actually_has():
    # The one assertion tying this file to the running system. Rename a tool in
    # agent/factory.py and the golden set stops matching it — silently, because
    # "the model did not call open_pr" and "open_pr no longer exists" score the
    # same. This makes the second one a red test instead.
    from agent.factory import TOOLS

    assert set(ToolName.__args__) == set(TOOLS), (
        "evals/schema.py's ToolName has drifted from agent/factory.py's registry"
    )


def test_every_declared_forbidden_behaviour_is_used_by_at_least_one_case():
    # A vocabulary entry no case uses is a scorer branch no case exercises.
    used = {b for case in CASES for b in case.forbidden_behaviors}
    assert used == set(ForbiddenBehavior.__args__), (
        f"unused vocabulary: {set(ForbiddenBehavior.__args__) - used}"
    )


def test_a_majority_of_cases_come_from_something_that_really_happened():
    # The drill's claim: a golden set is a statement about real jobs. Authored
    # cases are legitimate — the adversarial fixtures cannot be anything else —
    # but they must not be the bulk of it.
    observed = [c for c in CASES if not c.origin.startswith("authored")]
    assert len(observed) / len(CASES) > 0.6


def test_the_set_keeps_cases_this_system_currently_fails():
    # A set built from what already passes measures the system against itself.
    known_failures = [c for c in CASES if "known-failure" in c.context_tags]
    assert len(known_failures) >= 3


def test_an_unknown_forbidden_behaviour_is_refused():
    with pytest.raises(Exception):
        GoldenCase.model_validate(_mutate(forbidden_behaviors=["be_unhelpful"]))


def test_an_unregistered_tool_name_is_refused():
    with pytest.raises(Exception):
        GoldenCase.model_validate(_mutate(expected_tools=["deploy_to_prod"]))


def test_a_full_agent_run_without_preconditions_is_refused():
    row = _mutate(tier="agent_run")
    row.pop("setup", None)
    with pytest.raises(Exception, match="setup"):
        GoldenCase.model_validate(row)


def test_a_case_that_asserts_nothing_is_refused():
    with pytest.raises(Exception, match="cannot fail"):
        GoldenCase.model_validate(_mutate(
            expected_tools=[], forbidden_behaviors=[],
            expected_citations_contains=[], must_refuse=False,
        ))


def test_an_unknown_setup_key_is_refused():
    # extra="forbid": a precondition the harness will never read is worse than
    # no precondition, because the case looks configured.
    with pytest.raises(Exception):
        GoldenCase.model_validate(_mutate(setup={"temperature": 0}))


def test_duplicate_ids_are_refused(tmp_path):
    doubled = tmp_path / "golden.jsonl"
    line = CASES[0].model_dump_json(by_alias=True, exclude_none=True)
    doubled.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case id"):
        load_golden(doubled)


def test_a_broken_line_names_its_line_number(tmp_path):
    broken = tmp_path / "golden.jsonl"
    broken.write_text("{}\nnot json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="golden.jsonl:1"):
        load_golden(broken)


def test_the_content_hash_moves_when_a_byte_does(tmp_path):
    original = tmp_path / "a.jsonl"
    original.write_text("{}\n", encoding="utf-8")
    before = content_hash(original)
    original.write_text("{} \n", encoding="utf-8")
    assert content_hash(original) != before


# --- the freeze -------------------------------------------------------------

def test_the_set_still_matches_the_frozen_version():
    # The whole point of a frozen hash: a change to the golden set cannot pass
    # unnoticed. This test failing is not a defect — it is the notification.
    # Edit golden.jsonl deliberately, then bump evals/golden.lock.json in the
    # same commit, and the diff records what moved and why.
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert content_hash() == lock["sha256"], (
        "evals/golden.jsonl has changed since it was frozen. If that was "
        "intended, update evals/golden.lock.json in the same commit."
    )


def test_the_frozen_counts_describe_the_set_they_lock():
    # A lock whose numbers drifted from its own hash would still pass the test
    # above while describing something else to anyone reading it.
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert lock["cases"] == len(CASES)
    assert lock["split"] == split_counts(CASES)
    assert lock["observed_origin"] == sum(
        1 for c in CASES if not c.origin.startswith("authored")
    )


def test_freezing_an_unchanged_set_is_a_no_op():
    # A freeze that rewrites the date on every run produces a diff of its own,
    # and a lock that changes without the set changing means nothing.
    from evals.freeze import build_lock

    assert build_lock(**{
        "version": json.loads(LOCK_PATH.read_text(encoding="utf-8"))["version"],
        "frozen_at": json.loads(LOCK_PATH.read_text(encoding="utf-8"))["frozen_at"],
    }) == json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def test_the_lock_can_be_rebuilt_from_the_set_alone():
    # The lock the repository carries must be reproducible by anyone running
    # the script, not only by whoever first typed the numbers in.
    from evals.freeze import build_lock

    rebuilt = build_lock()
    stored = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert {k: v for k, v in rebuilt.items() if k != "frozen_at"} == {
        k: v for k, v in stored.items() if k != "frozen_at"
    }


def test_ci_runs_the_gate_the_makefile_documents():
    # The Makefile calls `test` the CI gate. A workflow that spells the same
    # command out a second time drifts from it silently, and the copy CI runs
    # is the one that wins.
    workflow = (GOLDEN_PATH.parent.parent / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "run: make test" in workflow
