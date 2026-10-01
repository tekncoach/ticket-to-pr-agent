"""The operator's switches: stop the agent, or stop one tool.

Hermetic: no model, no key, no network. The loop under test is the real one,
driven by a scripted model, because a test that restates the dispatch rule
proves the restatement and not the runtime.

Two properties matter more than the rest. Each switch is read on the call, so a
change reaches a runtime that is already running. And each fails closed: a typo
in the value must leave the agent off, not on, because the person flipping it
at 3 a.m. is not the person who wrote it.
"""
from unittest.mock import patch

import anthropic
import pytest
from fastapi.testclient import TestClient

from agent.config import agent_enabled, disabled_tools
from agent.event_sink import NullSink
from agent.runtime import AgentRuntime, Tool, ToolResult

# --- the values ------------------------------------------------------------

def test_the_agent_is_enabled_when_nothing_is_set(monkeypatch):
    # Unlike SHADOW_MODE, whose default is the safe state, the default here is
    # the working state: a deployment that never heard of this switch runs.
    monkeypatch.delenv("AGENT_ENABLED", raising=False)
    assert agent_enabled() is True


@pytest.mark.parametrize("value", ["true", "TRUE", "True", " true "])
def test_only_true_keeps_the_agent_on(monkeypatch, value):
    monkeypatch.setenv("AGENT_ENABLED", value)
    assert agent_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", "", "flase", "ture", "true;"])
def test_anything_else_turns_the_agent_off_including_a_typo(monkeypatch, value):
    # The direction a mistake falls is the design. A kill switch that stays
    # armed-but-open on "flase" is a switch that did not work and said nothing.
    monkeypatch.setenv("AGENT_ENABLED", value)
    assert agent_enabled() is False


def test_disabled_tools_reads_a_comma_list_and_ignores_the_blanks(monkeypatch):
    monkeypatch.setenv("DISABLED_TOOLS", " open_pr, comment_on_ticket ,,")
    assert disabled_tools() == {"open_pr", "comment_on_ticket"}


def test_no_tool_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DISABLED_TOOLS", raising=False)
    assert disabled_tools() == set()


# --- through the real loop -------------------------------------------------

def _message(calls):
    return anthropic.types.Message.model_validate({
        "id": "msg_fake", "model": "m", "role": "assistant", "type": "message",
        "stop_reason": "tool_use" if calls else "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": args}
                    for i, (name, args) in enumerate(calls)],
    })


def _drive(runtime, turns):
    scripted = iter(turns)

    def fake_llm(messages, tools):
        try:
            return _message(next(scripted))
        except StopIteration:
            return _message([])

    with patch.object(runtime, "_llm", side_effect=fake_llm):
        return runtime.run("go")


@pytest.fixture
def spy(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    calls = []
    tool = Tool(name="open_pr",
                handler=lambda a: (calls.append(a), ToolResult(ok=True, data="opened"))[1],
                input_schema={"type": "object", "properties": {}})
    return calls, tool


def _runtime(tool, **kw):
    return AgentRuntime(model="m", tools={tool.name: tool}, system="s", logger=NullSink(), **kw)


def _results(run):
    return [e for e in run["trace"] if e["event"] == "tool_result"]


def test_a_disabled_tool_is_refused_and_never_runs(monkeypatch, spy):
    calls, tool = spy
    monkeypatch.setenv("DISABLED_TOOLS", "open_pr")
    run = _drive(_runtime(tool, disabled_tools=disabled_tools), [[("open_pr", {})]])

    assert calls == [], "the handler must not run"
    [result] = _results(run)
    assert result["ok"] is False
    assert result["error_code"] == "denied: tool disabled by operator: open_pr"
    assert result["error_class"] == "denied"


def test_flipping_it_reaches_a_runtime_that_is_already_built(monkeypatch, spy):
    # The same object, two runs, the env changed between them. A switch frozen
    # at construction would let the second one through.
    calls, tool = spy
    monkeypatch.delenv("DISABLED_TOOLS", raising=False)
    runtime = _runtime(tool, disabled_tools=disabled_tools)

    _drive(runtime, [[("open_pr", {})]])
    assert len(calls) == 1

    monkeypatch.setenv("DISABLED_TOOLS", "open_pr")
    _drive(runtime, [[("open_pr", {})]])
    assert len(calls) == 1, "the second run must have been refused"

    monkeypatch.setenv("DISABLED_TOOLS", "")
    _drive(runtime, [[("open_pr", {})]])
    assert len(calls) == 2, "and clearing it brings the tool back"


def test_disabling_one_tool_leaves_the_others_alone(monkeypatch, spy):
    calls, tool = spy
    other = Tool(name="reader", handler=lambda a: ToolResult(ok=True, data="read"),
                 input_schema={"type": "object", "properties": {}})
    monkeypatch.setenv("DISABLED_TOOLS", "open_pr")
    runtime = AgentRuntime(model="m", tools={"open_pr": tool, "reader": other}, system="s",
                           logger=NullSink(), disabled_tools=disabled_tools)
    run = _drive(runtime, [[("reader", {})]])
    [result] = _results(run)
    assert result["ok"] is True


# --- the service -----------------------------------------------------------

@pytest.fixture
def client():
    from agent.service import app
    return TestClient(app)


def test_a_disabled_agent_refuses_a_run_before_anything_else(monkeypatch, client):
    # Before the key check, before GitHub, before the model: a switched-off
    # agent that still calls out to check a label is not off.
    monkeypatch.setenv("AGENT_ENABLED", "false")
    with patch("agent.service.check_ready", side_effect=AssertionError("GitHub was called")), \
         patch("agent.service._get_runtime", side_effect=AssertionError("a runtime was built")):
        response = client.post("/v1/run", json={"issue": 13})

    assert response.status_code == 503
    assert "disabled by operator" in response.json()["error"]
    assert "AGENT_ENABLED" in response.json()["error"]


def test_a_disabled_agent_refuses_chat_too(monkeypatch, client):
    monkeypatch.setenv("AGENT_ENABLED", "false")
    with patch("agent.service._get_runtime", side_effect=AssertionError("a runtime was built")):
        assert client.post("/v1/chat", json={"message": "hi"}).status_code == 503


def test_health_says_what_is_on_so_the_operator_can_confirm_the_flip(monkeypatch, client):
    # The drill's last step: not "I set it" but "it says it is set".
    monkeypatch.setenv("AGENT_ENABLED", "false")
    monkeypatch.setenv("DISABLED_TOOLS", "open_pr,comment_on_tikcet")
    body = client.get("/health").json()
    assert body["agent_enabled"] is False
    assert body["disabled_tools"] == ["comment_on_tikcet", "open_pr"]
    # A misspelt tool name disables nothing. /health is where that shows up.
    assert body["disabled_tools_unknown"] == ["comment_on_tikcet"]


def test_health_reports_a_running_agent_with_nothing_disabled(monkeypatch, client):
    monkeypatch.delenv("AGENT_ENABLED", raising=False)
    monkeypatch.delenv("DISABLED_TOOLS", raising=False)
    body = client.get("/health").json()
    assert body["agent_enabled"] is True
    assert body["disabled_tools"] == [] and body["disabled_tools_unknown"] == []


# --- the command line ------------------------------------------------------

def test_the_cli_refuses_when_the_agent_is_disabled(monkeypatch, capsys):
    from agent import cli

    monkeypatch.setenv("AGENT_ENABLED", "false")
    monkeypatch.setattr("sys.argv", ["agent.cli", "hello"])
    with patch.object(cli, "build_runtime", side_effect=AssertionError("a runtime was built")):
        with pytest.raises(SystemExit) as exit_info:
            cli.main()
    assert exit_info.value.code != 0
    assert "disabled by operator" in capsys.readouterr().err


# --- the deployment --------------------------------------------------------

def test_compose_hands_both_switches_to_the_container():
    # Compose passes a container only the variables it names. Adding a switch
    # to the code and not to this list sets it on the host and changes nothing
    # inside, which is a kill switch that does nothing and says nothing.
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(
        (Path(__file__).parent.parent / "deploy" / "docker-compose.yml").read_text())
    env = next(iter(compose["services"].values()))["environment"]
    assert {"SHADOW_MODE", "AGENT_ENABLED", "DISABLED_TOOLS"} <= set(env)
    # And the defaults are the working state, not an accidental off.
    assert env["AGENT_ENABLED"] == "${AGENT_ENABLED:-true}"
    assert env["DISABLED_TOOLS"] == "${DISABLED_TOOLS:-}"
