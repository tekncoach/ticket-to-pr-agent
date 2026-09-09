"""Regression test: a network/API failure inside _llm() must not crash the
process — AgentRuntime.run() should catch it and return a bounded
llm_call_failed result instead of propagating the exception.

Coach's review after Fix #2 landed: "llm_call_error is emitted and
returned, but nothing in this diff shows a test asserting that path ...
right now that fix is proven by inspection, not by a red test." This is
that test.

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
    # The scoping the coach called out: catching anthropic.APIError
    # specifically, not bare Exception, means a real bug elsewhere (e.g. in
    # _anthropic_tools()) must still propagate instead of being laundered
    # into "the LLM failed."
    runtime = _runtime(monkeypatch)

    with patch.object(runtime, "_llm", side_effect=ValueError("not an API error")):
        with pytest.raises(ValueError):
            runtime.run("does not matter")
