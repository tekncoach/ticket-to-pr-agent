"""Unit tests for the get_time tool.

Pure and deterministic — no LLM call, no live service, no key required. This is
the "test the non-LLM pieces" rubric line: exactly the unit you can pin down
without a model in the loop.

Targets tools.get_time (the Tool actually registered in agent/cli.py), not
hello_agent.py's original version — that one predates the Tool/ToolResult
contract and returned a bare string instead of a ToolResult.
"""

from datetime import datetime

from tools.get_time import get_time


def test_default_is_utc():
    result = get_time.handler({})
    assert result.ok
    offset = datetime.fromisoformat(result.data).utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_valid_iana_zone():
    result = get_time.handler({"timezone": "Europe/Paris"})
    assert result.ok
    offset = datetime.fromisoformat(result.data).utcoffset()
    assert offset is not None
    # Paris is UTC+1 (winter) or UTC+2 (summer/DST).
    assert offset.total_seconds() in (3600, 7200)


def test_unknown_zone_is_a_structured_failure():
    result = get_time.handler({"timezone": "Mars/Olympus"})
    assert not result.ok
    assert result.error_code == "unknown_timezone"
