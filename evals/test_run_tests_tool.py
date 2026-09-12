"""Unit tests for run_tests. Hermetic — subprocess.run is mocked and
TARGET_PYTHON is patched to a file that exists, so these need no target repo
checkout and no installed suite.

The two properties worth protecting: a red suite is a successful call, and
nothing raw reaches the model.
"""
import subprocess
from unittest.mock import patch

import pytest

from tools.run_tests import MAX_FAILURES_REPORTED, run_tests

GREEN = "..........\n10 passed in 0.42s\n"

RED = """..F..F
=========================== short test summary info ============================
FAILED tests/test_db.py::test_insert - AssertionError: expected 3, got 2
FAILED tests/test_app.py::test_share - KeyError: 'token'
2 failed, 4 passed, 1 skipped in 1.31s
"""


def _call(arguments=None, stdout=GREEN, stderr="", returncode=0, python_exists=True):
    completed = subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr,
    )
    with patch("tools.run_tests.subprocess.run", return_value=completed) as run, \
         patch("tools.run_tests.TARGET_PYTHON") as python:
        python.exists.return_value = python_exists
        python.__str__ = lambda self: "/target/.venv/bin/python"
        result = run_tests.handler(arguments or {})
    return result, run


def test_a_green_suite_reports_counts():
    result, _ = _call()
    assert result.ok
    assert result.data["green"] is True
    assert result.data["passed"] == 10
    assert result.data["failed"] == 0
    assert result.data["duration_s"] == 0.42


def test_a_red_suite_is_a_successful_call():
    # The decision this tool rests on. agent/runtime.py discards
    # ToolResult.data when ok is False and forwards only the error_code, so
    # reporting a red suite as a failure would throw away the list of failing
    # tests — which is the one thing the agent needs to fix the code.
    result, _ = _call(stdout=RED, returncode=1)
    assert result.ok
    assert result.data["green"] is False
    assert result.data["passed"] == 4
    assert result.data["failed"] == 2
    assert result.data["skipped"] == 1


def test_each_failure_carries_its_test_id_and_reason():
    result, _ = _call(stdout=RED, returncode=1)
    failures = result.data["failures"]
    assert [f["test"] for f in failures] == [
        "tests/test_db.py::test_insert", "tests/test_app.py::test_share",
    ]
    assert failures[0]["message"] == "AssertionError: expected 3, got 2"


def test_nothing_raw_reaches_the_model():
    # docs/SDLC-schema.md's contract: a summary, never the stdout dump. A full
    # run is thousands of tokens of noise and none of it is decision-relevant
    # beyond what and where.
    noisy = "x" * 50_000 + "\n" + RED
    result, _ = _call(stdout=noisy, returncode=1)
    assert "x" * 100 not in str(result.data)
    assert set(result.data) == {
        "passed", "failed", "errors", "skipped", "duration_s",
        "failures", "failures_truncated", "stderr", "green",
    }


def test_a_wall_of_failures_is_capped_and_says_so():
    # Fifty failing tests are telling the agent one thing, not fifty.
    lines = "\n".join(
        f"FAILED tests/test_x.py::test_{i} - AssertionError: nope" for i in range(25)
    )
    result, _ = _call(stdout=f"{lines}\n25 failed in 2.0s\n", returncode=1)
    assert len(result.data["failures"]) == MAX_FAILURES_REPORTED
    assert result.data["failures_truncated"] == 25 - MAX_FAILURES_REPORTED


def test_a_long_failure_message_is_truncated():
    long_message = "AssertionError: " + "y" * 5000
    result, _ = _call(stdout=f"FAILED tests/a.py::b - {long_message}\n1 failed in 0.1s\n", returncode=1)
    assert len(result.data["failures"][0]["message"]) <= 300


def test_the_selector_reaches_pytest():
    _, run = _call({"selector": "tests/test_db.py::test_insert"})
    assert run.call_args[0][0][-1] == "tests/test_db.py::test_insert"


def test_no_selector_runs_the_whole_suite():
    _, run = _call()
    assert not any(arg.startswith("tests/") for arg in run.call_args[0][0])


@pytest.mark.parametrize("selector", ["../../../etc", "/etc/passwd", "../outside/tests/x.py::t"])
def test_a_selector_escaping_the_workspace_is_refused(selector):
    # A selector is a path and it comes from the model. pytest would collect
    # from outside the workspace happily — the same confinement every other
    # tool applies to a model-supplied path applies here.
    result, run = _call({"selector": selector})
    assert result.error_code.startswith("denied: selector escapes workspace")
    assert not run.called, "refused before anything ran"


def test_a_selector_with_a_test_suffix_is_still_allowed():
    # The ::test_name part is not a path component and must not fail the check.
    result, _ = _call({"selector": "tests/test_db.py::test_insert"})
    assert result.ok


@pytest.mark.parametrize("selector", ["", "   ", 42])
def test_a_malformed_selector_is_a_validation_error(selector):
    result, run = _call({"selector": selector})
    assert result.error_code == "validation: selector must be a non-empty string"
    assert not run.called


def test_a_missing_test_environment_says_which_path_is_missing():
    result, run = _call(python_exists=False)
    assert result.error_code.startswith("internal: no test environment at ")
    assert not run.called


def test_a_timeout_is_reported_as_a_timeout():
    with patch("tools.run_tests.subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 300)), \
         patch("tools.run_tests.TARGET_PYTHON") as python:
        python.exists.return_value = True
        result = run_tests.handler({})
    assert result.error_code.startswith("timeout: test suite exceeded")


@pytest.mark.parametrize("returncode, prefix", [
    (5, "validation: no tests matched"),
    (4, "validation: pytest usage error"),
    (3, "internal: pytest exited 3"),
    (2, "internal: pytest exited 2"),
])
def test_pytest_exit_codes_map_onto_the_taxonomy(returncode, prefix):
    result, _ = _call(stdout="", stderr="something", returncode=returncode)
    assert result.error_code.startswith(prefix)


def test_stderr_surfaces_only_when_there_is_nothing_else_to_go_on():
    # A crash before pytest could report anything leaves an empty summary,
    # which would otherwise read as a clean run of zero tests.
    crashed, _ = _call(stdout="", stderr="ImportError: no module named app", returncode=1)
    assert crashed.data["stderr"] == "ImportError: no module named app"

    normal, _ = _call(stdout=RED, stderr="a deprecation warning", returncode=1)
    assert normal.data["stderr"] is None


def test_it_is_not_a_write_tool():
    # Running tests executes the target repo's code, but changes nothing
    # outside the run's own container — so it is not gated by SHADOW_MODE.
    assert run_tests.side_effect is False
