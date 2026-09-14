"""Conversation-level recovery: what the run does when a tool keeps failing.

The assertions here are unusual on purpose — several of them are about the
wording of the final answer, not about control flow. That is deliberate. A run
that gives up is still answering a person, and an error code is a log line, not
an answer. The sentence is the deliverable.

Hermetic: AgentRuntime._llm is patched, so no API call and no real key.
"""
from unittest.mock import patch

import pytest

from agent.errors import ErrorClass, ToolError
from agent.event_sink import NullSink
from agent.runtime import AgentRuntime, Tool, ToolResult


class _Block:
    def __init__(self, name, arguments, block_id="b1"):
        self.type = "tool_use"
        self.name = name
        self.input = arguments
        self.id = block_id

    def model_dump(self):
        return {"type": "tool_use", "name": self.name, "input": self.input}


class _Response:
    """One assistant turn asking for one tool call."""

    def __init__(self, name, arguments, index):
        self.content = [_Block(name, arguments, f"b{index}")]
        self.stop_reason = "tool_use"
        self.id = f"msg_{index}"
        self.model = "claude-haiku-4-5"
        self.stop_details = None
        self.usage = type("U", (), {
            "input_tokens": 1, "output_tokens": 1, "output_tokens_details": None,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "service_tier": "standard",
        })()


def _runtime(monkeypatch, tools, **kwargs):
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-fake-key-for-tests")
    return AgentRuntime(
        model="claude-haiku-4-5", tools=tools, system="s",
        logger=NullSink(), **kwargs,
    )


def _always_calls(name):
    """An LLM that asks for the same tool with slightly different arguments —
    not identical, so the duplicate-call guard never fires."""
    counter = {"n": 0}

    def _llm(messages, tools):
        counter["n"] += 1
        return _Response(name, {"attempt": counter["n"]}, counter["n"])

    return _llm, counter


def _failing_tool(name, error_code):
    return Tool(
        name=name,
        handler=lambda arguments: ToolResult(ok=False, error_code=error_code),
        input_schema=None,
    )


def test_an_auth_failure_stops_the_run_on_the_first_occurrence(monkeypatch):
    # The drill's answer, enforced: an auth failure is neither transient nor
    # recoverable by the agent, so it must not be handed back to the model to
    # route around.
    tool = _failing_tool("fetch_ticket", str(ToolError(ErrorClass.AUTH, "HTTP 401")))
    runtime = _runtime(monkeypatch, {"fetch_ticket": tool})
    llm, counter = _always_calls("fetch_ticket")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        result = runtime.run("go")

    assert result["error"] == "auth_failure"
    assert counter["n"] == 1, "no further turn may be taken after an auth failure"
    assert result["trace"][-1]["event"] == "auth_failure"


def test_the_auth_answer_says_nothing_else_was_tried(monkeypatch):
    tool = _failing_tool("fetch_ticket", str(ToolError(ErrorClass.AUTH, "HTTP 401")))
    runtime = _runtime(monkeypatch, {"fetch_ticket": tool})
    llm, _ = _always_calls("fetch_ticket")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        answer = runtime.run("go")["answer"]

    assert "fetch_ticket" in answer
    assert "did not try anything else" in answer
    assert "credentials need renewing" in answer


def test_a_tool_failing_twice_in_a_row_stops_the_run(monkeypatch):
    tool = _failing_tool("bash", str(ToolError(ErrorClass.UNAVAILABLE, "HTTP 503")))
    runtime = _runtime(monkeypatch, {"bash": tool})
    llm, counter = _always_calls("bash")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        result = runtime.run("go")

    assert result["error"] == "repeated_tool_failure"
    assert counter["n"] == 2, "stopped on the second failure, not at max_turns"


@pytest.mark.parametrize("error_code, expected_step", [
    (str(ToolError(ErrorClass.RATE_LIMIT, "HTTP 429")), "wait for the rate-limit window"),
    (str(ToolError(ErrorClass.UNAVAILABLE, "HTTP 503")), "run this ticket again once it is back"),
    (str(ToolError(ErrorClass.DENIED, "crypto.py")), "a human has to decide"),
    (str(ToolError(ErrorClass.NOT_FOUND, "issue 9")), "check the identifier exists"),
    (str(ToolError(ErrorClass.INTERNAL, "KeyError")), "a bug in the agent"),
])
def test_the_final_answer_proposes_a_next_step_for_the_class(monkeypatch, error_code, expected_step):
    # The drill's point about the 429: what the person ends up seeing is not
    # the retry, it is a sentence they can act on. Each class gets its own.
    tool = _failing_tool("bash", error_code)
    runtime = _runtime(monkeypatch, {"bash": tool})
    llm, _ = _always_calls("bash")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        answer = runtime.run("go")["answer"]

    assert expected_step in answer
    assert error_code in answer, "the typed code is named, not hidden"


def test_the_final_answer_is_a_sentence_not_an_error_code(monkeypatch):
    tool = _failing_tool("bash", str(ToolError(ErrorClass.RATE_LIMIT, "HTTP 429")))
    runtime = _runtime(monkeypatch, {"bash": tool})
    llm, _ = _always_calls("bash")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        answer = runtime.run("go")["answer"]

    assert answer.endswith(".")
    assert len(answer.split()) > 12, "an answer a person can act on, not a code"
    assert "failed 2 times in a row" in answer


def test_a_success_resets_the_streak_so_self_correction_still_works(monkeypatch):
    # An agent that fails, fixes its arguments and succeeds is doing exactly
    # what it should. Only consecutive failures count, or the guard would cut
    # off the recovery it exists to encourage.
    outcomes = iter([
        ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "ambiguous"))),
        ToolResult(ok=True, data="fixed"),
        ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "ambiguous"))),
        ToolResult(ok=True, data="fixed"),
    ])
    tool = Tool(name="edit", handler=lambda arguments: next(outcomes), input_schema=None)
    runtime = _runtime(monkeypatch, {"edit": tool}, max_turns=4)
    llm, counter = _always_calls("edit")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        result = runtime.run("go")

    assert result["error"] == "max_turns", "never stopped early: no two failures were consecutive"
    assert counter["n"] == 4


def test_the_threshold_is_configurable(monkeypatch):
    tool = _failing_tool("bash", str(ToolError(ErrorClass.UNAVAILABLE, "HTTP 503")))
    runtime = _runtime(monkeypatch, {"bash": tool}, max_consecutive_tool_failures=3, max_turns=6)
    llm, counter = _always_calls("bash")

    with patch.object(AgentRuntime, "_llm", side_effect=llm):
        result = runtime.run("go")

    assert result["error"] == "repeated_tool_failure"
    assert counter["n"] == 3


def test_two_different_tools_failing_once_each_does_not_stop_the_run(monkeypatch):
    # The streak is per tool. One failure each is not a spin, it is an agent
    # working through its options.
    tools = {
        "a": _failing_tool("a", str(ToolError(ErrorClass.NOT_FOUND, "x"))),
        "b": _failing_tool("b", str(ToolError(ErrorClass.NOT_FOUND, "y"))),
    }
    runtime = _runtime(monkeypatch, tools, max_turns=2)
    names = iter(["a", "b"])

    def _llm(messages, tools):
        return _Response(next(names), {"n": 1}, 1)

    with patch.object(AgentRuntime, "_llm", side_effect=_llm):
        result = runtime.run("go")

    assert result["error"] == "max_turns"


def test_the_system_prompt_teaches_the_taxonomy_it_will_actually_receive():
    # The runtime handles the run it abandons. This covers the other half: a
    # tool failing once while the run continues, where what the user sees is
    # whatever the model decides to say. A prompt naming classes the code does
    # not emit would be worse than none.
    from agent.errors import ErrorClass
    from agent.factory import TOOL_FAILURES

    for error_class in ErrorClass:
        assert error_class.value in TOOL_FAILURES, f"{error_class.value} is unmentioned"
    assert "do not try another tool to get around it" in TOOL_FAILURES
    assert "never report success you did not observe" in TOOL_FAILURES.lower()
