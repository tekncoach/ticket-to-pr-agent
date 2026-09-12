"""Unit tests for fetch_ticket, the one live external integration.

Hermetic: httpx.MockTransport answers every call through the tool's own
_build_client seam, so no network, no real token, and no real sleeping.
"""
from unittest.mock import patch

import httpx
import pytest

from tools.fetch_ticket import fetch_ticket
from tools.http_client import ResilientClient

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"


def _call(handler, arguments, token=FAKE_TOKEN, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv("GITHUB_TOKEN", token)

    def build(tok):
        return ResilientClient("https://api.github.com", tok, transport=httpx.MockTransport(handler))

    with patch("tools.fetch_ticket._build_client", build), patch("tools.http_client.time.sleep"):
        return fetch_ticket.handler(arguments)


def _answers(*responses):
    seen = []
    remaining = list(responses)

    def handler(request):
        seen.append(request)
        item = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def test_returns_title_and_body(monkeypatch):
    handler, seen = _answers(httpx.Response(200, json={"title": "Fix it", "body": "Do the fix"}))
    result = _call(handler, {"issue_id": 42}, monkeypatch=monkeypatch)
    assert result.ok
    assert result.data == {"title": "Fix it", "body": "Do the fix"}
    assert seen[0].url.path.endswith("/issues/42")


def test_missing_issue_id_is_a_validation_error(monkeypatch):
    handler, _ = _answers(httpx.Response(200, json={}))
    result = _call(handler, {}, monkeypatch=monkeypatch)
    assert result.error_code == "validation: missing issue_id"


def test_absent_token_is_an_auth_error(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handler, seen = _answers(httpx.Response(200, json={}))
    result = _call(handler, {"issue_id": 1})
    assert result.error_code == "auth: GITHUB_TOKEN is not set"
    assert not seen, "no request should be attempted without a token"


def test_missing_issue_is_not_found(monkeypatch):
    handler, seen = _answers(httpx.Response(404, json={"message": "Not Found"}))
    result = _call(handler, {"issue_id": 99999}, monkeypatch=monkeypatch)
    assert result.error_code == "not_found: HTTP 404"
    assert len(seen) == 1, "a 404 is final, not worth retrying"


def test_empty_body_is_a_validation_error(monkeypatch):
    handler, _ = _answers(httpx.Response(200, json={"title": "t", "body": "   "}))
    result = _call(handler, {"issue_id": 7}, monkeypatch=monkeypatch)
    assert result.error_code == "validation: issue #7 has an empty body"


def test_a_transient_500_is_retried_and_then_succeeds(monkeypatch):
    # The regression this migration exists for: before it, fetch_ticket had no
    # retry at all and a single 5xx failed the whole run.
    handler, seen = _answers(
        httpx.Response(500),
        httpx.Response(200, json={"title": "t", "body": "b"}),
    )
    result = _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert result.ok
    assert len(seen) == 2


def test_rate_limit_is_retried(monkeypatch):
    handler, seen = _answers(
        httpx.Response(429, headers={"retry-after": "1"}),
        httpx.Response(200, json={"title": "t", "body": "b"}),
    )
    result = _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert result.ok
    assert len(seen) == 2


def test_network_failure_reports_unavailable(monkeypatch):
    request = httpx.Request("GET", "https://api.github.com/x")
    handler, _ = _answers(httpx.ConnectError("connection reset", request=request))
    result = _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert result.error_code.startswith("unavailable:")


def test_github_headers_are_sent(monkeypatch):
    handler, seen = _answers(httpx.Response(200, json={"title": "t", "body": "b"}))
    _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert seen[0].headers["accept"] == "application/vnd.github+json"
    assert seen[0].headers["x-github-api-version"] == "2022-11-28"


@pytest.mark.parametrize("field", ["title", "body"])
def test_a_secret_pasted_into_an_issue_is_redacted(monkeypatch, field):
    # An Issue is written by anyone: a key pasted into a repro example must
    # not travel out of this tool and into the run's JSONL trace.
    payload = {"title": "t", "body": "b"}
    payload[field] = f"see sk-ant-{'x' * 40} for the repro"
    handler, _ = _answers(httpx.Response(200, json=payload))
    result = _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert result.ok
    assert "sk-ant-" not in result.data[field]


def test_an_error_body_from_github_is_redacted_too(monkeypatch):
    # The failure path returns GitHub's own response body; it is no more
    # trusted than the success path's.
    handler, _ = _answers(httpx.Response(422, text=f"bad token sk-ant-{'x' * 40} rejected"))
    result = _call(handler, {"issue_id": 1}, monkeypatch=monkeypatch)
    assert not result.ok
    assert "sk-ant-" not in (result.data or "")
