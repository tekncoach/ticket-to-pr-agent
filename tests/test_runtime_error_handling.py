"""Regression test: a network/API failure inside _llm() must not crash the
process — AgentRuntime.run() should catch it and return a bounded
llm_call_failed result instead of propagating the exception.

llm_call_error was emitted and returned, but nothing asserted that path —
the behaviour was proven by inspection rather than by a red test. This is
that red test.

No live API call: AgentRuntime._llm is patched to raise directly, so this
needs no real network access and no real API key (a fake one satisfies
__post_init__'s presence check only, never sent anywhere).
"""
from unittest.mock import patch

import anthropic
import httpx
import pytest

from agent.event_sink import NullSink
from agent.runtime import AgentRuntime


def _fake_connection_error() -> anthropic.APIConnectionError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message="Connection error.", request=request)


def _runtime(monkeypatch) -> AgentRuntime:
    monkeypatch.setenv("LLM_API_KEY", "fake-key-for-init-only")
    return AgentRuntime(model="claude-haiku-4-5", tools={}, system="test", logger=NullSink())


def test_llm_connection_error_returns_bounded_failure_not_a_crash(monkeypatch):
    runtime = _runtime(monkeypatch)

    with patch.object(runtime, "_llm", side_effect=_fake_connection_error()):
        result = runtime.run("does not matter, _llm never actually runs")

    assert result["error"] == "llm_call_failed"
    assert "APIConnectionError" in result["answer"]
    assert result["trace"][-1]["event"] == "llm_call_error"
    assert result["trace"][-1]["error_type"] == "APIConnectionError"


def test_a_bug_in_our_own_code_still_crashes_loud(monkeypatch):
    # The scoping that makes this safe: catching anthropic.APIError
    # specifically, not bare Exception, means a real bug elsewhere (e.g. in
    # _anthropic_tools()) must still propagate instead of being laundered
    # into "the LLM failed."
    runtime = _runtime(monkeypatch)

    with patch.object(runtime, "_llm", side_effect=ValueError("not an API error")):
        with pytest.raises(ValueError):
            runtime.run("does not matter")


# --- prompt caching ---------------------------------------------------------

def test_the_conversation_carries_a_cache_breakpoint_at_its_end():
    # Every turn resends the whole history, so without this the same nine turns
    # are paid for at full price ten times. Measured on one multi-turn case:
    # 51,076 tokens read from cache against 3,089 fresh.
    from agent.runtime import AgentRuntime

    marked = AgentRuntime._with_cache_breakpoint(
        [{"role": "user", "content": "first"}, {"role": "assistant", "content": "second"}])
    assert marked[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in str(marked[0]), "only the last turn is marked"


def test_marking_does_not_mutate_the_loop_s_own_history():
    # The loop reuses its messages list every turn; leaving breakpoints behind
    # would stack past the four the API allows.
    from agent.runtime import AgentRuntime

    history = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    AgentRuntime._with_cache_breakpoint(history)
    assert "cache_control" not in str(history)


def test_an_empty_conversation_is_left_alone():
    from agent.runtime import AgentRuntime

    assert AgentRuntime._with_cache_breakpoint([]) == []


# --- the allowlist workaround guard (F23) -----------------------------------

def _message(calls):
    """A real SDK Message carrying tool_use blocks.

    Built from the actual types rather than a hand-rolled double: the runtime
    reads fields the SDK keeps adding, and a fake that has to grow a new
    attribute every release is a test that breaks for reasons unrelated to
    what it asserts.
    """
    return anthropic.types.Message.model_validate({
        "id": "msg_fake", "model": "m", "role": "assistant", "type": "message",
        "stop_reason": "tool_use" if calls else "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": args}
                    for i, (name, args) in enumerate(calls)],
    })


def _drive(runtime, turns):
    """Run the loop over a scripted sequence of tool calls per turn."""
    scripted = iter(turns)

    def fake_llm(messages, tools):
        try:
            return _message(next(scripted))
        except StopIteration:
            return _message([])

    with patch.object(runtime, "_llm", side_effect=fake_llm):
        return runtime.run("go")


def test_the_leading_executable_is_read_naively_on_purpose():
    # The guard it feeds is narrow, and a parser trying to be clever about
    # pipes and prefixes would refuse more than it should.
    from agent.runtime import _leading_executable

    assert _leading_executable("env | grep -i github") == "env"
    assert _leading_executable("  ls -la ") == "ls"
    assert _leading_executable("") is None


def test_a_second_binary_after_an_allowlist_refusal_stops_the_run(monkeypatch):
    # Observed in adv-004, the secret-exfiltration case: refused `env`, the
    # agent tried `printenv`. The anti-spin guard never saw it — those are
    # different calls — and naming it in the system prompt did not stop it.
    # F23: prose was not the mechanism.
    from agent.errors import ErrorClass, ToolError
    from agent.runtime import AgentRuntime, Tool, ToolResult

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    refusals = iter([
        ToolResult(ok=False, error_code=str(ToolError(
            ErrorClass.DENIED, "executable not allowed: env"))),
        ToolResult(ok=True, data="GITHUB_TOKEN=..."),
    ])
    bash = Tool(name="bash", handler=lambda _a: next(refusals),
                input_schema={"type": "object",
                              "properties": {"command": {"type": "string"}}})

    runtime = AgentRuntime(model="m", tools={"bash": bash}, system="s",
                           logger=NullSink())
    result = _drive(runtime, [
        [("bash", {"command": "env | grep -i github"})],
        [("bash", {"command": "printenv | grep -i github"})],
    ])
    assert result["error"] == "allowlist_workaround"
    assert "printenv" in result["answer"] and "env" in result["answer"]
    assert any(e["event"] == "allowlist_workaround_stop" for e in result["trace"])


def test_correcting_the_same_command_after_a_refusal_still_runs(monkeypatch):
    # Fixing a path or a flag is a correction, not a workaround. A blunter
    # guard would block legitimate exploration, which this repo has already
    # paid for once — six of eight blockers on its first completed ticket.
    from agent.errors import ErrorClass, ToolError
    from agent.runtime import AgentRuntime, Tool, ToolResult

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    results = iter([
        ToolResult(ok=False, error_code=str(ToolError(
            ErrorClass.DENIED, "executable not allowed: env"))),
        ToolResult(ok=True, data="ok"),
    ])
    bash = Tool(name="bash", handler=lambda _a: next(results),
                input_schema={"type": "object",
                              "properties": {"command": {"type": "string"}}})
    runtime = AgentRuntime(model="m", tools={"bash": bash}, system="s",
                           logger=NullSink())
    result = _drive(runtime, [
        [("bash", {"command": "env"})],
        [("bash", {"command": "env -0"})],
    ])
    assert result.get("error") != "allowlist_workaround"


def test_a_path_refused_by_one_tool_is_refused_through_the_next(monkeypatch):
    # F28: the executable memory was bash-only, so bash being refused for
    # /etc/passwd and the editor then being asked for the same file was
    # recorded nowhere. The editor refuses it independently — it has confined
    # paths since before any of this — so nothing leaks, and adv-006 was
    # passing for a reason unrelated to the guard it was written to test.
    # Reaching for another tool to obtain the refused thing is the behaviour.
    from agent.errors import ErrorClass, ToolError
    from agent.runtime import AgentRuntime, Tool, ToolResult

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    denied = ToolResult(ok=False, error_code=str(ToolError(
        ErrorClass.DENIED, "argument escapes workspace: /etc/passwd")))
    schema = {"type": "object", "properties": {"command": {"type": "string"},
                                               "path": {"type": "string"}}}
    tools = {
        "bash": Tool(name="bash", handler=lambda _a: denied, input_schema=schema),
        "str_replace_based_edit_tool": Tool(
            name="str_replace_based_edit_tool",
            handler=lambda _a: ToolResult(ok=True, data="root:x:0:0"),
            input_schema=schema),
    }
    runtime = AgentRuntime(model="m", tools=tools, system="s", logger=NullSink())
    result = _drive(runtime, [
        [("bash", {"command": "cat /etc/passwd"})],
        [("str_replace_based_edit_tool", {"command": "view", "path": "/etc/passwd"})],
    ])
    assert result["error"] == "refused_path_retry"
    assert "/etc/passwd" in result["answer"]
    assert any(e["event"] == "refused_path_retry_stop" for e in result["trace"])


def test_a_different_path_after_a_refusal_still_runs(monkeypatch):
    # Narrow on purpose: being refused one path does not end exploration of
    # the workspace, which is what a blunter guard would do.
    from agent.errors import ErrorClass, ToolError
    from agent.runtime import AgentRuntime, Tool, ToolResult

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    answers = iter([
        ToolResult(ok=False, error_code=str(ToolError(
            ErrorClass.DENIED, "argument escapes workspace: /etc/passwd"))),
        ToolResult(ok=True, data="app.py"),
    ])
    bash = Tool(name="bash", handler=lambda _a: next(answers),
                input_schema={"type": "object",
                              "properties": {"command": {"type": "string"}}})
    runtime = AgentRuntime(model="m", tools={"bash": bash}, system="s",
                           logger=NullSink())
    result = _drive(runtime, [
        [("bash", {"command": "cat /etc/passwd"})],
        [("bash", {"command": "ls ."})],
    ])
    assert result.get("error") != "refused_path_retry"


def test_no_comment_claims_a_feature_is_absent_that_is_wired_up():
    # Two comments said thinking was never requested and no cache breakpoints
    # existed, months after both were built. A comment that contradicts the
    # code beneath it is worse than none: it is read as current.
    import inspect

    from agent import runtime

    source = inspect.getsource(runtime)
    assert "we never request thinking" not in source
    assert "no cache_control breakpoints yet" not in source


def test_a_relative_token_is_never_remembered_as_a_refused_path():
    # F30: bash checks every argument, so `ls ..` produced "argument escapes
    # workspace: .." and the guard stored the two-character string. It then
    # substring-matched the serialised arguments of every later call, so a grep
    # pattern with an ellipsis, or a filename like a..b, killed the run with a
    # message about boundaries.
    from agent.runtime import _referenced_paths, _resolved_or_none

    assert _resolved_or_none("..") is None
    assert _resolved_or_none(".") is None
    assert _resolved_or_none("/etc/passwd") is not None
    assert _referenced_paths({"command": "grep -rn 'x...y' app.py"}) == set()
    assert _referenced_paths({"command": "cat /etc/passwd"})


def test_a_capped_call_may_be_reissued(monkeypatch):
    # F31: the signature was recorded before the parallel-call cap ran, so a
    # 7th call in one turn was refused without executing and still remembered
    # as done. Re-issuing it hit the anti-spin guard and ended the run saying
    # "trying again would not produce new information" — about a call that had
    # produced none.
    from agent.runtime import AgentRuntime, Tool, ToolResult

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    schema = {"type": "object", "properties": {"command": {"type": "string"}}}
    bash = Tool(name="bash", handler=lambda _a: ToolResult(ok=True, data="ok"),
                input_schema=schema)
    runtime = AgentRuntime(model="m", tools={"bash": bash}, system="s",
                           logger=NullSink(), max_parallel_tool_calls=2)
    result = _drive(runtime, [
        [("bash", {"command": f"ls {i}"}) for i in range(3)],
        [("bash", {"command": "ls 2"})],
    ])
    assert result.get("error") != "duplicate_tool_call"


def test_every_stop_the_runtime_emits_is_declared_terminal():
    # F35: two stop events were added with new guards and never added to the
    # service's terminal set, so a run the runtime killed on purpose rendered
    # as still going and its stop sentence — the only thing that says why —
    # never reached the page.
    import inspect
    import re

    from agent import runtime, service

    emitted = set(re.findall(r'"event": "(\w*?_stop|final|\w*?_error|\w*?_failure)"',
                             inspect.getsource(runtime)))
    missing = {e for e in emitted if e.endswith("_stop")} - service._TERMINAL_EVENTS
    assert not missing, f"the runtime stops on {missing} and the service does not know"
