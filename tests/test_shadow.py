"""Shadow mode. Hermetic — no model, no network.

Three properties, each named by a drill: reads stay live and only the
consequence is removed, redaction happens before anything reaches disk, and
our own flag is never the proof that nothing was written.
"""
import json

import pytest

from shadow.audit import compare
from shadow.runner import redact, redact_deep


# --- redaction, at write time -----------------------------------------------

def test_an_issue_body_loses_its_personal_data():
    # Traffic is written by members of the public: addresses, numbers, and the
    # handles that make a complaint attributable.
    out = redact("Ping bob.smith@example.com or +33 6 12 34 56 78, cc @maintainer")
    assert "[EMAIL]" in out and "[PHONE]" in out and "[HANDLE]" in out
    assert "bob.smith" not in out and "33 6 12" not in out and "@maintainer" not in out


def test_a_secret_is_removed_by_the_redactor_that_ships():
    assert "sk-ant-" not in redact(f"token sk-ant-{'x' * 40} here")


@pytest.mark.parametrize("kept", ["see issue 3349", "version 0.27.0", "HTTP 404 twice"])
def test_ordinary_numbers_survive(kept):
    # A redactor that eats version strings and issue numbers makes the log
    # unreadable, which is its own kind of data loss.
    assert redact(kept) == kept


def test_redaction_walks_the_values_and_leaves_the_structure():
    # Measured: redacting the serialised JSON let the phone pattern eat the
    # punctuation between fields — `"latency_ms": 1234.5, "x": 12` is a
    # plausible number once the quotes stop mattering — and produced records
    # that would not parse.
    record = {"latency_ms": 1234.5, "turns": 12, "who": "bob@example.com",
              "trace": [{"note": "+33 6 12 34 56 78"}]}
    out = redact_deep(record)
    assert out["latency_ms"] == 1234.5 and out["turns"] == 12
    assert out["who"] == "[EMAIL]" and out["trace"][0]["note"] == "[PHONE]"
    assert json.loads(json.dumps(out)) == out


# --- the audit, which is the only actual proof ------------------------------

def test_an_unchanged_integration_reports_nothing_moved():
    state = {"comments": {"13": "1"}, "pull_requests": "3", "branches": "4"}
    assert compare(state, state) == []


@pytest.mark.parametrize("field,changed", [
    ("comments", {"comments": {"13": "2"}, "pull_requests": "3", "branches": "4"}),
    ("pull_requests", {"comments": {"13": "1"}, "pull_requests": "4", "branches": "4"}),
    ("branches", {"comments": {"13": "1"}, "pull_requests": "3", "branches": "5"}),
])
def test_anything_a_write_would_move_is_caught(field, changed):
    before = {"comments": {"13": "1"}, "pull_requests": "3", "branches": "4"}
    moved = compare(before, changed)
    assert moved and field.split("_")[0] in moved[0]


def test_the_audit_reads_nothing_of_ours():
    # SHADOW_MODE, the write gate and the receipts are all ours, and a bug in
    # any of them produces the same reassuring output as a correct run. The
    # audit asks the system we did not write, and must not be tempted to
    # shortcut through our own logs.
    import ast
    import inspect

    from shadow import audit

    # Parsed, not grepped. The docstring explains at length why our own flag
    # and our own receipts are not evidence, and a grep for those words fails
    # the test that asserts they are unused — the same shape as the reporting
    # gate test in test_open_pr_tool.py.
    tree = ast.parse(inspect.getsource(audit))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value not in docstrings}
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}

    for ours in ("results.jsonl", "tmp/sessions", "SHADOW_MODE", "shadow_receipt"):
        assert not any(ours in lit for lit in literals), f"the audit must not consult {ours}"
    assert not any((m or "").startswith(("agent", "evals")) for m in imported), \
        "the audit must not reach into the system it is auditing"


# --- the harvest ------------------------------------------------------------

def test_the_harvester_is_not_bound_to_one_repository():
    # A shadow runner coupled to its own project cannot answer the question a
    # shadow run exists to ask.
    import inspect

    from shadow import harvest

    assert "--repo" in inspect.getsource(harvest.main)
    assert "liberty-rider" not in inspect.getsource(harvest)


def test_bots_are_not_traffic():
    from shadow.harvest import BOTS

    assert "dependabot" in BOTS


def test_a_write_returns_a_receipt_rather_than_a_refusal():
    # F40: the runner closed the runtime's write gate instead of making writes
    # no-ops. The gate answers DENIED, so the agent tried, was refused, tried
    # again and stopped on repeated_tool_failure without ever saying what it
    # would have changed. A gate says no; shadow says done.
    from agent.factory import TOOLS
    from shadow.runner import shadowed_tools

    recorded: list[dict] = []
    tools = shadowed_tools(TOOLS, recorded)
    result = tools["str_replace_based_edit_tool"].handler(
        {"command": "str_replace", "path": "httpx/_client.py",
         "old_str": "a", "new_str": "b"})

    assert result.ok, "a shadow write succeeds; only the consequence is removed"
    assert result.data["shadow"] is True
    assert result.data["intended_args"]["path"] == "httpx/_client.py"
    assert recorded and recorded[0]["arguments"]["new_str"] == "b"
    assert tools["open_pr"].side_effect is True, "the runtime's accounting is unchanged"


def test_viewing_a_file_is_not_recorded_as_a_write():
    # The editor is one tool with several commands. Counting a view inflated
    # writes_intended and put every file merely read into files_touched, which
    # is the comparison's own column.
    from agent.factory import TOOLS
    from shadow.runner import shadowed_tools

    recorded: list[dict] = []
    tools = shadowed_tools(TOOLS, recorded)
    tools["str_replace_based_edit_tool"].handler({"command": "view", "path": "httpx/_client.py"})
    assert recorded == []
