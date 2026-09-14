"""The write kill switch. Hermetic — no API call, no key, no network.

A kill switch that needs a restart is not a kill switch: its value is that
someone can stop writes mid-incident in seconds, without a rebuild and without
the author's laptop. These tests assert the switch takes effect on the next
tool call of a runtime that is already constructed and already running.
"""
from unittest.mock import patch

import pytest

from agent.config import shadow_mode, writes_allowed
from agent.errors import ErrorClass, classify
from agent.event_sink import NullSink
from agent.runtime import AgentRuntime, Tool, ToolResult


@pytest.fixture
def writing_tool():
    calls = []
    return calls, Tool(
        name="writer",
        handler=lambda arguments: (calls.append(arguments), ToolResult(ok=True, data="wrote"))[1],
        input_schema=None,
        side_effect=True,
    )


def _runtime(monkeypatch, tool, gate):
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-fake-key-for-tests")
    return AgentRuntime(
        model="claude-haiku-4-5", tools={"writer": tool}, system="s",
        logger=NullSink(), allow_side_effects=gate,
    )


def _call_tool(runtime, tool_name="writer"):
    """Exercise the gate the way the dispatch loop does, without an LLM."""
    tool = runtime.tools[tool_name]
    if tool.side_effect and not runtime._writes_allowed():
        return ToolResult(ok=False, error_code="denied: side effects are not allowed in this run")
    return tool.handler({})


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("TRUE", True), ("True", True),
    ("false", False), ("FALSE", False), ("anything-else", False),
])
def test_shadow_mode_reads_the_env_each_time(monkeypatch, value, expected):
    monkeypatch.setenv("SHADOW_MODE", value)
    assert shadow_mode() is expected
    assert writes_allowed() is not expected


def test_it_defaults_to_shadow_when_unset(monkeypatch):
    # The safe default: an unconfigured deployment does not write.
    monkeypatch.delenv("SHADOW_MODE", raising=False)
    assert shadow_mode() is True
    assert writes_allowed() is False


def test_flipping_the_switch_takes_effect_without_rebuilding_the_runtime(monkeypatch, writing_tool):
    # The defect this replaces: allow_side_effects was computed once, at import
    # time, and baked into the runtime at construction. Changing the env then
    # did nothing until the process restarted.
    calls, tool = writing_tool
    monkeypatch.setenv("SHADOW_MODE", "true")
    runtime = _runtime(monkeypatch, tool, writes_allowed)

    blocked = _call_tool(runtime)
    assert classify(blocked.error_code) is ErrorClass.DENIED
    assert not calls

    monkeypatch.setenv("SHADOW_MODE", "false")
    allowed = _call_tool(runtime)
    assert allowed.ok
    assert len(calls) == 1

    # And back, on the same runtime object: a switch that only opens is a
    # release note, not a kill switch.
    monkeypatch.setenv("SHADOW_MODE", "true")
    assert classify(_call_tool(runtime).error_code) is ErrorClass.DENIED
    assert len(calls) == 1


def test_a_plain_boolean_gate_still_works(monkeypatch, writing_tool):
    # Every existing caller and test passes a bool. The callable form is an
    # addition, not a replacement.
    calls, tool = writing_tool
    assert _runtime(monkeypatch, tool, True)._writes_allowed() is True
    assert _runtime(monkeypatch, tool, False)._writes_allowed() is False


def test_the_health_endpoint_reports_the_live_value(monkeypatch):
    # The field an operator refreshes to confirm the switch actually took.
    from agent.service import health

    monkeypatch.setenv("SHADOW_MODE", "true")
    assert health()["shadow_mode"] is True
    assert health()["shadow_enforced"] is True, "there is a write tool to gate"

    monkeypatch.setenv("SHADOW_MODE", "false")
    assert health()["shadow_mode"] is False
    assert health()["shadow_enforced"] is False


def test_every_write_tool_reads_the_same_switch(monkeypatch):
    # Three checks existed, each with its own copy of the env read. One
    # definition now, so they cannot drift into disagreeing about what is on.
    import tools.comment_on_ticket as comment
    import tools.open_pr as pr

    assert comment.shadow_mode is shadow_mode
    assert pr.shadow_mode is shadow_mode


def test_a_write_tool_refuses_on_its_own_even_if_the_gate_is_opened(monkeypatch):
    # Defence in depth: opening the runtime's gate must not be enough, by
    # itself, to start writing to a real repository.
    monkeypatch.setenv("SHADOW_MODE", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_fake")
    from tools.open_pr import open_pr

    # open_pr re-reads the agent:ready contract before writing, so consent has
    # to be granted here for shadow mode to be the thing under test.
    from agent.runtime import ToolResult as _TR
    with patch("tools.open_pr._changed_files", return_value=["app.py"]), \
         patch("tools.open_pr.check_ready", return_value=_TR(ok=True, data={"number": 1})), \
         patch("tools.open_pr._build_client") as client:
        client.return_value.__enter__.return_value.request.return_value = ToolResult(ok=True, data=[])
        result = open_pr.handler({"issue_id": 1, "title": "t"})

    assert result.ok
    assert "SHADOW_MODE" in result.data
    assert "nothing pushed" in result.data
