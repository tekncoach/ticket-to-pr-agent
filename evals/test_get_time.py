"""Unit tests for the get_time tool.

Pure and deterministic — no LLM call, no live service, no key required. This is
the "test the non-LLM pieces" rubric line: exactly the unit you can pin down
without a model in the loop.
"""

from datetime import datetime

import hello_agent


def test_default_is_utc():
    result = hello_agent.get_time({})
    offset = datetime.fromisoformat(result).utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_valid_iana_zone():
    result = hello_agent.get_time({"timezone": "Europe/Paris"})
    offset = datetime.fromisoformat(result).utcoffset()
    assert offset is not None
    # Paris is UTC+1 (winter) or UTC+2 (summer/DST).
    assert offset.total_seconds() in (3600, 7200)


def test_unknown_zone_returns_error_string():
    result = hello_agent.get_time({"timezone": "Mars/Olympus"})
    assert result.startswith("Error:")
    assert "Mars/Olympus" in result
