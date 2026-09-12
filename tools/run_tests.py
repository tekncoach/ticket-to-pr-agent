# tools/run_tests.py
#
# Runs the target repo's own test suite — the local gate before open_pr, and
# the only oracle the edit->test loop has between edits.
#
# Two things decide this tool's shape.
#
# 1. It returns a summary, never raw output. A full pytest run is thousands of
#    tokens of noise, and none of it is decision-relevant beyond "did it pass,
#    and if not, what and where". docs/SDLC-schema.md fixed this as a contract
#    for whoever built this tool; condensing happens here, before the model
#    ever sees it.
#
# 2. Failing tests are ok=True. The tool did its job — the red suite IS the
#    answer, and it is the one the agent needs in order to fix the code. This
#    is not a stylistic call: agent/runtime.py discards ToolResult.data when
#    ok is False and sends only the error_code, so reporting a red suite as a
#    failure would throw away the list of failing tests. ok=False is reserved
#    for the tool itself failing — no environment, bad selector, timeout.
#
# The target repo's dependencies are pinned separately from ours, so its suite
# runs under its own interpreter (agent.config.TARGET_PYTHON), not the one
# executing this file.
from __future__ import annotations

import re
import subprocess

from agent.config import TARGET_PYTHON, WORKSPACE
from agent.errors import ErrorClass, ToolError
from agent.runtime import Tool, ToolResult
from agent.workspace_guard import resolve_within_workspace

TIMEOUT_S = 300
# Enough to fix something, few enough to stay a summary. A suite failing in
# fifty places is telling the agent one thing, not fifty.
MAX_FAILURES_REPORTED = 10
MAX_MESSAGE_CHARS = 300

_COUNTS_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed|deselected)")
_DURATION_RE = re.compile(r"in ([\d.]+)s")
_FAILED_RE = re.compile(r"^(?:FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)

# pytest's own exit codes. 1 is "tests failed", which is a result, not an error.
_EXIT_TESTS_FAILED = 1
_EXIT_INTERRUPTED = 2
_EXIT_INTERNAL_ERROR = 3
_EXIT_USAGE_ERROR = 4
_EXIT_NO_TESTS_COLLECTED = 5


def _fail(error_class: ErrorClass, detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(error_class, detail)))


def _summarise(stdout: str, stderr: str) -> dict:
    counts = {name: int(n) for n, name in _COUNTS_RE.findall(stdout)}
    duration = _DURATION_RE.search(stdout)
    failures = [
        {"test": test, "message": (message or "").strip()[:MAX_MESSAGE_CHARS]}
        for test, message in _FAILED_RE.findall(stdout)
    ]
    return {
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "errors": counts.get("error", 0) + counts.get("errors", 0),
        "skipped": counts.get("skipped", 0),
        "duration_s": float(duration.group(1)) if duration else None,
        "failures": failures[:MAX_FAILURES_REPORTED],
        "failures_truncated": max(0, len(failures) - MAX_FAILURES_REPORTED),
        # Only when there is nothing else to go on: a crash before pytest could
        # report anything leaves an empty summary that would otherwise read as
        # a clean run with zero tests.
        "stderr": stderr.strip()[:MAX_MESSAGE_CHARS] if stderr.strip() and not counts else None,
    }


def _handler(arguments: dict) -> ToolResult:
    selector = arguments.get("selector")
    if selector is not None:
        if not isinstance(selector, str) or not selector.strip():
            return _fail(ErrorClass.VALIDATION, "selector must be a non-empty string")
        # A selector is a path, and it comes from the model. Same confinement
        # every other tool applies to model-supplied paths — pytest would
        # happily collect tests from outside the workspace otherwise. The
        # ::test_name suffix is stripped first: it is not part of the path.
        if resolve_within_workspace(WORKSPACE, selector.split("::", 1)[0]) is None:
            return _fail(ErrorClass.DENIED, f"selector escapes workspace: {selector}")

    if not TARGET_PYTHON.exists():
        return _fail(
            ErrorClass.INTERNAL,
            f"no test environment at {TARGET_PYTHON} — the target repo's "
            "dependencies are not installed",
        )

    command = [
        str(TARGET_PYTHON), "-m", "pytest",
        # -q keeps the dots, --tb=line keeps one line per failure instead of a
        # traceback, -rf is what produces the parseable FAILED summary lines.
        "-q", "--tb=line", "-rf", "--no-header",
        # The target repo is a working tree the agent edits between runs; a
        # stale cache is a source of results that do not match the files.
        "-p", "no:cacheprovider",
    ]
    if selector:
        command.append(selector)

    try:
        proc = subprocess.run(
            command, cwd=WORKSPACE, capture_output=True, text=True, timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return _fail(ErrorClass.TIMEOUT, f"test suite exceeded {TIMEOUT_S}s")

    if proc.returncode == _EXIT_NO_TESTS_COLLECTED:
        return _fail(ErrorClass.VALIDATION, f"no tests matched: {selector or '(whole suite)'}")
    if proc.returncode == _EXIT_USAGE_ERROR:
        return _fail(ErrorClass.VALIDATION, f"pytest usage error: {proc.stderr.strip()[:MAX_MESSAGE_CHARS]}")
    if proc.returncode in (_EXIT_INTERRUPTED, _EXIT_INTERNAL_ERROR):
        return _fail(ErrorClass.INTERNAL, f"pytest exited {proc.returncode}: {proc.stderr.strip()[:MAX_MESSAGE_CHARS]}")

    summary = _summarise(proc.stdout, proc.stderr)
    summary["green"] = proc.returncode == 0
    return ToolResult(ok=True, data=summary)


run_tests = Tool(
    name="run_tests",
    description=(
        "Run the target repo's test suite and return a summary: pass/fail "
        "counts and the failing tests with a one-line reason each. Optionally "
        "narrow to one file or test with a selector. A red suite is a "
        "successful call — read 'green' and 'failures' in the result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": (
                    "Optional pytest selector inside the repo, e.g. "
                    "'tests/test_db.py' or 'tests/test_db.py::test_insert'. "
                    "Omit to run everything."
                ),
            },
        },
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=False,
)
