"""Regression test: GITHUB_TOKEN must never appear anywhere in a tool's
output — because agent/runtime.py's emit() serializes ToolResult.data
directly into the persisted JSONL trace. If the token ever leaked into
ToolResult, it would leak into every log file for that run too.

Coach's Day 3 review: "No secrets-in-logs check anywhere (GITHUB_TOKEN
never logged, but nothing asserts that)." This is that assertion.

No live GitHub call: httpx.get is mocked, so this needs no real network
access and no real token — GITHUB_TOKEN is a fake, distinctive value for
the duration of each test only (pytest's monkeypatch reverts it after).
"""
import json
from unittest.mock import MagicMock, patch

from tools.fetch_ticket import fetch_ticket

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"


def _fake_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    return resp


def test_token_never_appears_in_a_successful_result(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    fake_resp = _fake_response(200, {"title": "Fix the thing", "body": "Do the fix"})

    with patch("httpx.get", return_value=fake_resp) as mock_get:
        result = fetch_ticket.handler({"issue_id": 1})

    assert result.ok
    # Mirrors agent/runtime.py's own tool_result content-building: a string
    # as-is, else json.dumps(...) — the exact form that lands in the JSONL
    # log, not just the raw ToolResult object.
    logged_content = result.data if isinstance(result.data, str) else json.dumps(result.data)
    assert FAKE_TOKEN not in logged_content

    # The token IS sent to GitHub — that's its whole purpose — but only in
    # the Authorization header, which is never what gets logged.
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_token_never_appears_in_a_failed_result(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    fake_resp = _fake_response(404)

    with patch("httpx.get", return_value=fake_resp):
        result = fetch_ticket.handler({"issue_id": 99999})

    assert not result.ok
    logged_content = (result.error_code or "") + str(result.data or "")
    assert FAKE_TOKEN not in logged_content
