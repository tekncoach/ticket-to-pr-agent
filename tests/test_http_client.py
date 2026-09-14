"""Unit tests for ResilientClient. Hermetic — httpx.MockTransport answers
every request, so there is no network, no key, and no real sleeping
(time.sleep is patched, and asserted on where the delay is the point).
"""
from unittest.mock import patch

import httpx
import pytest

from tools.http_client import (
    MAX_DELAY_S,
    ResilientClient,
    _backoff_delay,
    idempotency_key,
)


def _client(handler, **kwargs):
    return ResilientClient(
        "https://api.example.com", "fake-token",
        transport=httpx.MockTransport(handler), **kwargs,
    )


def _always(status, *, headers=None, json_body=None, text=""):
    """A handler answering every request identically, recording each one."""
    seen = []

    def handler(request):
        seen.append(request)
        if json_body is not None:
            return httpx.Response(status, json=json_body, headers=headers)
        return httpx.Response(status, text=text, headers=headers)

    return handler, seen


def _sequence(*responses):
    """A handler walking a fixed list of responses, one per request."""
    seen = []
    remaining = list(responses)

    def handler(request):
        seen.append(request)
        item = remaining.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def test_success_returns_parsed_json():
    handler, seen = _always(200, json_body={"number": 42})
    with _client(handler) as client:
        result = client.request("GET", "/issues/42")
    assert result.ok
    assert result.data == {"number": 42}
    assert len(seen) == 1


def test_success_with_empty_body_returns_none():
    handler, _ = _always(204)
    with _client(handler) as client:
        result = client.request("DELETE", "/issues/42")
    assert result.ok
    assert result.data is None


@pytest.mark.parametrize("status, expected", [
    (401, "auth: HTTP 401"),
    (403, "denied: HTTP 403"),
    (404, "not_found: HTTP 404"),
    (422, "validation: HTTP 422"),
])
def test_terminal_statuses_are_not_retried(status, expected):
    handler, seen = _always(status)
    with _client(handler) as client:
        result = client.request("GET", "/issues/1")
    assert not result.ok
    assert result.error_code == expected
    assert len(seen) == 1, "a terminal failure must not be retried"


def test_error_body_is_carried_back_truncated():
    handler, _ = _always(422, text="x" * 900)
    with _client(handler) as client:
        result = client.request("GET", "/issues/1")
    assert result.data == "x" * 500


def test_rate_limit_then_success():
    handler, seen = _sequence(
        httpx.Response(429), httpx.Response(200, json={"ok": True}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.ok
    assert len(seen) == 2


def test_exhausted_retries_report_the_last_real_error_not_a_fixed_one():
    # The defect this replaces: looping and then returning a hardcoded
    # RATE_LIMIT meant four 500s were reported as a rate limit. Whatever
    # actually failed last is what comes back.
    handler, seen = _always(500)
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.error_code == "unavailable: HTTP 500 after 4 attempts"
    assert len(seen) == 4


def test_retry_after_header_is_honoured():
    handler, _ = _sequence(
        httpx.Response(429, headers={"retry-after": "60"}),
        httpx.Response(200, json={}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep") as sleep:
        client.request("GET", "/issues/1")
    sleep.assert_called_once_with(60.0)


def test_retry_after_is_capped():
    handler, _ = _sequence(
        httpx.Response(429, headers={"retry-after": "99999"}),
        httpx.Response(200, json={}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep") as sleep:
        client.request("GET", "/issues/1")
    sleep.assert_called_once_with(MAX_DELAY_S)


def test_unparseable_retry_after_falls_back_to_backoff():
    handler, _ = _sequence(
        httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200, json={}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep") as sleep:
        client.request("GET", "/issues/1")
    assert 0 < sleep.call_args[0][0] <= 0.5


def test_403_with_retry_after_is_a_rate_limit_not_a_refusal():
    # GitHub's secondary rate limit is a 403 carrying Retry-After. Without
    # this, every one of them reads as a permissions failure and never retries.
    handler, seen = _sequence(
        httpx.Response(403, headers={"retry-after": "1"}),
        httpx.Response(200, json={}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.ok
    assert len(seen) == 2


def test_403_without_retry_after_stays_a_refusal():
    handler, seen = _always(403)
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.error_code == "denied: HTTP 403"
    assert len(seen) == 1


def test_a_write_is_not_retried_without_an_idempotency_key():
    # The dangerous one: a retried POST that already created an issue creates
    # a second. The failure is retryable, the request is not.
    handler, seen = _always(500)
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("POST", "/issues", json={"title": "x"})
    assert len(seen) == 1, "a non-idempotent write must be sent exactly once"
    assert result.error_code == (
        "unavailable: HTTP 500 (not retried: POST without an idempotency key)"
    )


def test_a_write_with_an_idempotency_key_is_retried_and_sends_the_header():
    key = idempotency_key("bot", "open_pr", {"branch": "fix-1"})
    handler, seen = _sequence(
        httpx.Response(500), httpx.Response(201, json={"number": 7}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("POST", "/issues", json={"title": "x"}, idempotency_key=key)
    assert result.ok
    assert len(seen) == 2
    assert all(r.headers["idempotency-key"] == key for r in seen)


def test_timeout_is_retried_then_reported_as_timeout():
    handler, seen = _always(200)

    def timing_out(request):
        handler(request)
        raise httpx.ConnectTimeout("timed out")

    with _client(timing_out) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.error_code.startswith("timeout:")
    assert result.error_code.endswith("after 4 attempts")
    assert len(seen) == 4


def test_network_error_is_retried_then_succeeds():
    # The template returned NETWORK immediately and never retried, though a
    # reset connection is exactly the transient case worth repeating.
    handler, seen = _sequence(
        httpx.ConnectError("connection reset"), httpx.Response(200, json={}),
    )
    with _client(handler) as client, patch("tools.http_client.time.sleep"):
        result = client.request("GET", "/issues/1")
    assert result.ok
    assert len(seen) == 2


def test_auth_header_is_sent():
    handler, seen = _always(200, json_body={})
    with _client(handler) as client:
        client.request("GET", "/issues/1")
    assert seen[0].headers["authorization"] == "Bearer fake-token"


def test_backoff_grows_and_stays_jittered_within_bounds():
    for attempt in range(4):
        ceiling = min(0.5 * (2 ** attempt), MAX_DELAY_S)
        delays = {_backoff_delay(attempt, None) for _ in range(50)}
        assert all(ceiling / 2 <= d <= ceiling for d in delays)
        assert len(delays) > 1, "no jitter: simultaneous callers would retry in lockstep"


def test_backoff_prefers_the_servers_own_number():
    assert _backoff_delay(0, retry_after=12.0) == 12.0


def test_idempotency_key_is_stable_and_intent_specific():
    a = idempotency_key("bot", "open_pr", {"branch": "fix-1"})
    assert a == idempotency_key("bot", "open_pr", {"branch": "fix-1"})
    assert a != idempotency_key("bot", "open_pr", {"branch": "fix-2"})
    assert a != idempotency_key("bot", "comment", {"branch": "fix-1"})
    assert a != idempotency_key("someone-else", "open_pr", {"branch": "fix-1"})


def test_idempotency_key_ignores_payload_key_order():
    assert idempotency_key("bot", "a", {"x": 1, "y": 2}) == idempotency_key("bot", "a", {"y": 2, "x": 1})
