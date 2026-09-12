"""Regression test: GITHUB_TOKEN must never appear anywhere in a tool's
output — because agent/runtime.py's emit() serializes ToolResult.data
directly into the persisted JSONL trace. If the token ever leaked into
ToolResult, it would leak into every log file for that run too.

GITHUB_TOKEN is never logged today, but nothing asserted that until this
test — an invariant nothing enforces is an invariant that decays.

No live GitHub call: httpx.MockTransport answers through fetch_ticket's
_build_client seam, so this needs no network and no real token — the value
below is fake and distinctive, set for the duration of each test only.
"""
import json
from unittest.mock import patch

import httpx

from tools.fetch_ticket import fetch_ticket
from tools.http_client import ResilientClient

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"


def _call_with_response(response, arguments):
    """Run fetch_ticket against one canned response, returning (result, requests)."""
    seen = []

    def handler(request):
        seen.append(request)
        return response

    def build(token):
        return ResilientClient(
            "https://api.github.com", token, transport=httpx.MockTransport(handler),
        )

    with patch("tools.fetch_ticket._build_client", build), patch("tools.http_client.time.sleep"):
        return fetch_ticket.handler(arguments), seen


def test_token_never_appears_in_a_successful_result(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    response = httpx.Response(200, json={"title": "Fix the thing", "body": "Do the fix"})

    result, seen = _call_with_response(response, {"issue_id": 1})

    assert result.ok
    # Mirrors agent/runtime.py's own tool_result content-building: a string
    # as-is, else json.dumps(...) — the exact form that lands in the JSONL
    # log, not just the raw ToolResult object.
    logged_content = result.data if isinstance(result.data, str) else json.dumps(result.data)
    assert FAKE_TOKEN not in logged_content

    # The token IS sent to GitHub — that's its whole purpose — but only in
    # the Authorization header, which is never what gets logged.
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_TOKEN}"


def test_token_never_appears_in_a_failed_result(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)

    result, _ = _call_with_response(httpx.Response(404, text="Not Found"), {"issue_id": 99999})

    assert not result.ok
    logged_content = (result.error_code or "") + str(result.data or "")
    assert FAKE_TOKEN not in logged_content


def test_token_never_leaks_through_an_error_body_that_echoes_it(monkeypatch):
    # The nastiest shape, and the one no pattern can catch: an API that
    # reflects the credential back in its own error text. Shape-based rules
    # only match what looks like a secret; the token we hold is known exactly,
    # so it is scrubbed by value before any pattern runs.
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    echoing = httpx.Response(422, text=f"token {FAKE_TOKEN} is malformed")

    result, _ = _call_with_response(echoing, {"issue_id": 1})

    assert not result.ok
    assert FAKE_TOKEN not in (result.error_code or "") + str(result.data or "")
