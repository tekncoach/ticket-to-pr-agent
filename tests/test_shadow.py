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


# --- the comparator ---------------------------------------------------------

def _record(files_touched, baseline_files, stopped_on=None, answer="done"):
    return {"request_id": "encode-httpx-1", "latency_ms": 100.0,
            "input_tokens": 10, "output_tokens": 5,
            "baseline": {"source": "merged-pull-request", "files": baseline_files},
            "agent_proposal": {"answer": answer, "files_touched": files_touched,
                               "stopped_on": stopped_on}}


def test_an_absolute_path_matches_a_repo_relative_one():
    # The agent works in absolute paths and the baseline is repo-relative, so
    # without this nothing ever matches and the metric reads 0.0 forever.
    from shadow.diff import classify

    row = classify(_record(["/repo/httpx/_transports/asgi.py"],
                           ["httpx/_transports/asgi.py"]))
    assert row["verdict"] == "agreed" and row["missed"] == []


def test_a_changelog_entry_is_not_evidence_of_finding_the_place():
    # Every pull request touches one and it says nothing about where the work
    # is; counting it would inflate agreement on every single unit.
    from shadow.diff import classify

    row = classify(_record(["/repo/httpx/_transports/asgi.py"],
                           ["CHANGELOG.md", "httpx/_transports/asgi.py"]))
    assert row["verdict"] == "agreed"


def test_touching_the_wrong_file_is_a_disagreement():
    from shadow.diff import classify

    row = classify(_record(["/repo/httpx/_client.py"], ["docs/advanced/transports.md"]))
    assert row["verdict"] == "disagreed"
    assert row["missed"] == ["docs/advanced/transports.md"]


def test_a_run_the_runtime_stopped_did_not_reach_a_proposal():
    # The stop sentence lives in the answer field, so checking for an empty
    # answer reported all three guard-killed units as finished and the
    # guardrail read 1.0. A guardrail existing and a guardrail working are
    # different claims.
    from shadow.diff import classify

    row = classify(_record(["/repo/httpx/_transports/asgi.py"],
                           ["httpx/_transports/asgi.py"],
                           stopped_on="allowlist_workaround",
                           answer="Stopping: the allowlist refused cd..."))
    assert row["verdict"] == "incomplete"


def test_agreement_is_not_reported_when_nothing_finished():
    # Agreement over the units that survived is the number that flatters
    # itself, which is what the guardrail exists to prevent.
    from shadow.diff import summarise

    summary = summarise([_record(["/repo/a.py"], ["a.py"], stopped_on="max_turns")])
    assert summary["file_agreement"]["of_finished"] is None
    assert summary["completion_rate"] == 0.0


def test_a_missing_baseline_is_named_rather_than_counted():
    from shadow.diff import classify, summarise

    record = _record(["/repo/a.py"], [])
    assert classify(record)["verdict"] == "baseline-unavailable"
    assert summarise([record])["completion_rate"] is None


def test_cost_stays_none_until_a_price_is_configured():
    # Same rule as the eval metrics: a hardcoded vendor price goes stale in
    # silence, and the staleness surfaces as a number nobody can defend.
    from shadow.diff import summarise

    assert summarise([_record(["/repo/a.py"], ["a.py"])])["cost_usd_per_unit"] is None


@pytest.mark.parametrize("touched,wanted,verdict", [
    # exact
    (["httpx/_client.py"], ["httpx/_client.py"], "agreed"),
    # the agent's absolute path against the PR's relative one
    (["/repo/httpx/_client.py"], ["httpx/_client.py"], "agreed"),
    (["/Users/x/clones/encode-httpx/httpx/_client.py"], ["httpx/_client.py"], "agreed"),
    # a suffix that is a whole path component, not a coincidence
    (["_client.py"], ["httpx/_client.py"], "agreed"),
    # same basename, different package — must NOT match
    (["httpx/_transports/utils.py"], ["httpx/_models/utils.py"], "disagreed"),
    # right place plus somewhere else
    (["httpx/_client.py", "httpx/_models.py"], ["httpx/_client.py"], "agreed"),
    # one of two
    (["httpx/_client.py"], ["httpx/_client.py", "tests/test_client.py"], "partial"),
    # nothing in common
    (["README.md"], ["httpx/_client.py"], "disagreed"),
])
def test_path_matching_at_the_edges(touched, wanted, verdict):
    # The metric is only as good as this comparison, and it was exercised
    # against three records — one of which happened to hit. A false "agreed"
    # baked into a number is worse than no number.
    from shadow.diff import classify

    assert classify(_record(touched, wanted))["verdict"] == verdict


def test_a_changelog_only_baseline_has_nothing_to_find():
    # Every pull request touches one. A baseline that is *only* noise leaves
    # nothing to agree with, and calling that a disagreement would blame the
    # agent for the filter.
    from shadow.diff import classify

    assert classify(_record(["httpx/_client.py"], ["CHANGELOG.md"]))["verdict"] \
        == "baseline-unavailable"


def test_the_shadow_prompt_names_the_workspace_it_dropped_the_agent_in(monkeypatch, tmp_path):
    # F42. The prompt said "you are inside a checkout of that repository" and
    # stopped there. The agent guessed /repo/httpx/... and the workspace guard
    # refused it — in all three units, before anything else went wrong.
    # agent/tickets.py::task_prompt has named the path since day 4; this one
    # was written without reading it.
    from shadow.runner import shadow_prompt

    prompt = shadow_prompt({"repo": "encode/httpx", "issue": 3111,
                            "title": "t", "body": "b"}, tmp_path)
    assert str(tmp_path) in prompt
    assert "/repo" in prompt, "it must name the path the agent invented, to forbid it"
    # The two constraints the other three stops came from.
    assert "editor" in prompt and "run_tests" in prompt


# --- what the agent actually tried on traffic it did not own ----------------
#
# F43 and F44 were written down as open modes with a named next step and
# nothing a future fix could prove itself against. Every other row in the
# sheet carries a case_id and a test; these carry the shapes below.
#
# They assert the refusal, which is today's behaviour and not the behaviour we
# want. The Claude SDK permission-mode migration is expected to make the
# editor reachable without the agent reaching for a shell at all — when it
# lands, these tests are what say whether it worked, and either they change
# with a stated reason or the migration did not fix the mode.

def _bash(tmp_path, command):
    from unittest.mock import patch
    from tools.bash import bash
    with patch("tools.bash.WORKSPACE", tmp_path):
        return bash.handler({"command": command})


@pytest.mark.parametrize("attempt", [
    # Straight out of the first batch's traces: with no write path in bash the
    # agent improvises one rather than reaching for the editor tool.
    "python3 << EOF\nprint(1)\nEOF",
    "python -c \"open('httpx/_client.py','a').write('x')\"",
    "cat > httpx/_client.py",
    "echo x >> httpx/_client.py",
    "sed -i 's/a/b/' httpx/_client.py",
])
def test_f43_the_shell_is_not_a_write_path_however_the_agent_asks(tmp_path, attempt):
    result = _bash(tmp_path, attempt)
    assert not result.ok, f"{attempt!r} would be a write through bash"
    assert result.error_code.startswith("denied:")


def test_f44_pytest_on_a_foreign_clone_is_refused_at_the_executable(tmp_path):
    # run_tests needs the target's own interpreter and a clone has none, so the
    # agent tries the suite directly. It is refused at the allowlist, which is
    # correct and also the end of its loop: on traffic we do not own there is
    # no green suite to converge to at all. That scope limit is stated in
    # shadow/README.md rather than papered over.
    for attempt in ("python -m pytest tests/", "pytest tests/test_asgi.py"):
        result = _bash(tmp_path, attempt)
        assert not result.ok
        assert "executable not allowed" in result.error_code


def test_f42_the_path_the_agent_invented_is_still_refused(tmp_path):
    # The prompt now names the workspace (F42), which is a mitigation. The
    # guard is the thing that must not regress: if /repo ever resolves, a
    # shadow run reads files from outside the checkout it claims to be in.
    result = _bash(tmp_path, "cat /repo/httpx/_client.py")
    assert not result.ok
    assert "escapes workspace" in result.error_code


# --- partial is two findings wearing one word ------------------------------

ID = "encode-httpx-1"


def _partial():
    # The agent touched one of the two files the pull request changed.
    return _record(["httpx/_transports/asgi.py"],
                   ["httpx/_transports/asgi.py", "tests/test_asgi.py"])


def test_an_unadjudicated_partial_does_not_count_as_agreement():
    # "Found half the fix" and "touched a file that happens to overlap" are
    # different findings and nothing deterministic separates them. Rounding a
    # partial up is how an unverified judgement gets baked into the headline.
    from shadow.diff import summarise

    s = summarise([_partial()])
    assert s["file_agreement"]["of_finished"] == 0.0
    assert s["file_agreement"]["partials_awaiting_adjudication"] == [ID]


def test_a_partial_called_half_the_fix_counts_and_one_called_coincidental_does_not():
    from shadow.diff import summarise

    half = summarise([_partial()], {ID: {"call": "half-the-fix", "why": "the asgi change is the fix; the test is its cover"}})
    assert half["file_agreement"]["of_finished"] == 1.0
    assert half["file_agreement"]["partials_awaiting_adjudication"] == []

    coincidental = summarise([_partial()], {ID: {"call": "coincidental", "why": "touched it to read a constant"}})
    assert coincidental["file_agreement"]["of_finished"] == 0.0


def test_a_call_that_is_not_one_of_the_two_is_not_a_call(tmp_path):
    # A free-text verdict in the queue must not silently count. Only the two
    # named calls are calls; anything else is still waiting.
    from shadow.diff import load_adjudications

    q = tmp_path / "adjudications.json"
    q.write_text(json.dumps({ID: {"call": "looks fine", "why": ""},
                             "other": {"call": "half-the-fix", "why": "x"}}))
    assert list(load_adjudications(q)) == ["other"]


def test_the_queue_keeps_a_call_already_made_and_only_adds_new_partials():
    # A judgement made once and lost is a judgement made every time.
    from shadow.diff import adjudication_queue, classify

    rows = [classify(_partial())]
    existing = {ID: {"call": "coincidental", "why": "checked by hand"}}
    assert adjudication_queue(rows, existing) == existing

    fresh = adjudication_queue(rows, {})
    assert fresh[ID]["call"] is None
    assert fresh[ID]["missed"] == ["tests/test_asgi.py"]
