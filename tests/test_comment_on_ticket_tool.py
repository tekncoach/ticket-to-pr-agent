"""Unit tests for comment_on_ticket, the first tool that writes outside this
machine. Hermetic — httpx.MockTransport answers through the tool's own
_build_client seam, so no network, no real token, nothing posted anywhere.

The property under test throughout is that no sequence of failures and
retries can produce two comments for one intent.
"""
import json
from unittest.mock import patch

import httpx
import pytest

from tools.comment_on_ticket import _marker, comment_on_ticket
from tools.http_client import ResilientClient, idempotency_key

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    """Writes enabled by default; the shadow-mode tests opt back out."""
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("SHADOW_MODE", "false")


class FakeIssue:
    """A GitHub issue that accepts comments, and can be told to misbehave."""

    def __init__(self, post_outcomes=()):
        self.comments = []
        self.posts = []
        self._post_outcomes = list(post_outcomes)
        self._next_id = 100

    def handler(self, request):
        if request.method == "GET":
            return httpx.Response(200, json=self.comments)

        self.posts.append(request)
        # A post always lands unless an outcome says otherwise; an outcome of
        # None means "GitHub accepted it, then the response was lost".
        outcome = self._post_outcomes.pop(0) if self._post_outcomes else "ok"
        if outcome == "ok" or outcome is None:
            comment = {
                "id": self._next_id,
                # Parsed, not the raw envelope: a fake that stores the wrong
                # thing makes the duplicate check pass for the wrong reason.
                "body": json.loads(request.content)["body"],
                "html_url": f"https://github.com/o/r/issues/1#issuecomment-{self._next_id}",
            }
            self._next_id += 1
            self.comments.append(comment)
            if outcome is None:
                raise httpx.ConnectTimeout("response lost after the write landed")
            return httpx.Response(201, json=comment)
        return outcome


def _call(issue, arguments):
    def build(token):
        return ResilientClient(
            "https://api.github.com", token, transport=httpx.MockTransport(issue.handler),
        )

    with patch("tools.comment_on_ticket._build_client", build), \
         patch("tools.comment_on_ticket.time.sleep"), \
         patch("tools.http_client.time.sleep"):
        return comment_on_ticket.handler(arguments)


def test_posts_once_and_returns_a_readable_receipt():
    issue = FakeIssue()
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert result.ok
    assert result.data.startswith("commented on ")
    assert "#42" in result.data
    assert "issuecomment-100" in result.data
    assert len(issue.posts) == 1


def test_the_same_comment_twice_does_not_duplicate_it():
    # The whole point of the tool: the second call recognises its own earlier
    # comment by the key embedded in it, and reports instead of reposting.
    issue = FakeIssue()
    first = _call(issue, {"issue_id": 42, "body": "CI is green."})
    second = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert first.ok and second.ok
    assert second.data.startswith("already commented on ")
    assert "no duplicate posted" in second.data
    assert len(issue.posts) == 1, "the second call must not reach POST at all"


def test_a_different_body_is_a_different_intent_and_does_post():
    issue = FakeIssue()
    _call(issue, {"issue_id": 42, "body": "CI is green."})
    result = _call(issue, {"issue_id": 42, "body": "CI is red."})
    assert result.ok
    assert result.data.startswith("commented on ")
    assert len(issue.posts) == 2


def test_a_write_that_landed_but_reported_failure_is_not_reposted():
    # The failure transport-level retries cannot survive: GitHub accepted the
    # comment, then the connection dropped before the response came back. The
    # next cycle's read finds the marker and stops.
    issue = FakeIssue(post_outcomes=[None])
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert result.ok
    assert result.data.startswith("already commented on ")
    assert len(issue.posts) == 1, "exactly one comment reached GitHub"
    assert len(issue.comments) == 1


def test_a_transient_failure_that_did_not_land_is_retried_and_posts_once():
    issue = FakeIssue(post_outcomes=[httpx.Response(503)])
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert result.ok
    assert result.data.startswith("commented on ")
    assert len(issue.comments) == 1


def test_the_marker_is_invisible_and_carries_the_intent_key():
    issue = FakeIssue()
    _call(issue, {"issue_id": 42, "body": "CI is green."})
    posted = issue.comments[0]["body"]
    key = idempotency_key("tekncoach/liberty-rider-myroadtrips", "comment_on_ticket",
                          {"issue": 42, "body": "CI is green."})
    assert _marker(key) in posted
    assert posted.startswith("CI is green.")
    assert posted.strip().endswith("-->"), "the marker is an HTML comment, not visible text"


def test_dry_run_checks_for_duplicates_but_never_posts():
    issue = FakeIssue()
    result = _call(issue, {"issue_id": 42, "body": "CI is green.", "dry_run": True})
    assert result.ok
    assert result.data.startswith("would comment on ")
    assert "dry_run" in result.data
    assert not issue.posts
    assert not issue.comments


def test_shadow_mode_forces_a_dry_run_even_when_not_asked(monkeypatch):
    # The second lock. The runtime's write gate already blocks side-effect
    # tools in shadow mode; this makes opening that gate insufficient, on its
    # own, to start posting to a real repo.
    monkeypatch.setenv("SHADOW_MODE", "true")
    issue = FakeIssue()
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert result.ok
    assert "SHADOW_MODE" in result.data
    assert not issue.posts


def test_a_refusal_is_returned_without_retrying():
    issue = FakeIssue(post_outcomes=[httpx.Response(403, text="Resource not accessible")])
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert not result.ok
    assert result.error_code == "denied: HTTP 403"
    assert len(issue.posts) == 1, "a refusal is final; repeating it is pointless"


def test_persistent_failure_reports_the_cycle_count():
    issue = FakeIssue(post_outcomes=[httpx.Response(503)] * 20)
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert not result.ok
    assert result.error_code.endswith("after 3 cycles")
    assert not issue.comments


@pytest.mark.parametrize("arguments, expected", [
    ({"body": "x"}, "validation: missing issue_id"),
    ({"issue_id": 1}, "validation: missing body"),
    ({"issue_id": 1, "body": "   "}, "validation: missing body"),
])
def test_bad_arguments_are_rejected_before_any_request(arguments, expected):
    issue = FakeIssue()
    result = _call(issue, arguments)
    assert result.error_code == expected
    assert not issue.posts


def test_absent_token_is_an_auth_error(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    issue = FakeIssue()
    result = _call(issue, {"issue_id": 1, "body": "x"})
    assert result.error_code == "auth: GITHUB_TOKEN is not set"
    assert not issue.posts


def test_it_is_declared_as_a_write_so_the_runtime_gate_sees_it():
    assert comment_on_ticket.side_effect is True


def test_an_unreadable_issue_never_leads_to_a_second_post():
    # Found by the chaos checks, not by review: with every read failing and
    # every write landing-then-losing-its-response, the tool posted three
    # comments. "Could not look" was being read as "nothing is there".
    posted = []
    request = httpx.Request("GET", "https://api.github.com/x")

    def flaky(req):
        if req.method == "GET":
            raise httpx.ConnectError("reset", request=request)
        posted.append(json.loads(req.content)["body"])
        raise httpx.ConnectTimeout("response lost", request=request)

    issue = FakeIssue()
    issue.handler = flaky
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})

    assert len(posted) == 1, "unknown must never become post-it-again"
    assert not result.ok
    assert "could not be confirmed" in result.error_code
    assert "not reposting" in result.error_code


def test_a_first_read_failure_still_allows_the_first_post():
    # The other direction: before anything has been sent there is nothing to
    # duplicate, so an unreadable issue must not block the comment entirely.
    state = {"reads": 0}
    issue = FakeIssue()
    real = issue.handler
    request = httpx.Request("GET", "https://api.github.com/x")

    def first_read_fails(req):
        if req.method == "GET":
            state["reads"] += 1
            if state["reads"] == 1:
                raise httpx.ConnectError("reset", request=request)
        return real(req)

    issue.handler = first_read_fails
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})
    assert result.ok
    assert result.data.startswith("commented on ")
    assert len(issue.comments) == 1


def test_exhausted_cycles_keep_the_real_error_class():
    # Coach review, Day 5: the exhaustion path wrapped the code in a ToolError
    # declared INTERNAL. It read correctly only because nothing looked at the
    # class — and the taxonomy exists precisely to be looked at.
    from agent.errors import ErrorClass, classify, is_retryable

    issue = FakeIssue(post_outcomes=[httpx.Response(429, headers={"retry-after": "1"})] * 20)
    result = _call(issue, {"issue_id": 42, "body": "CI is green."})

    assert not result.ok
    assert classify(result.error_code) is ErrorClass.RATE_LIMIT
    assert is_retryable(result.error_code)
    assert result.error_code.startswith("rate_limit: "), "the class is not doubled"
    assert result.error_code.count("rate_limit") == 1
    assert result.error_code.endswith("gave up after 3 cycles")


def test_the_two_retry_layers_cannot_multiply_past_the_stated_cap():
    # Coach review, Day 5: 3 cycles over a client that retries 4 times reads
    # like 12 attempts against a rate limit. The read's budget is cut inside
    # the cycle so the layers add rather than multiply — this pins the number
    # rather than leaving it to be rediscovered.
    from tools.comment_on_ticket import MAX_CYCLES, MAX_REQUESTS, READ_ATTEMPTS

    assert MAX_REQUESTS == MAX_CYCLES * (READ_ATTEMPTS + 1) == 9

    seen = []

    def everything_fails(request):
        seen.append(request)
        return httpx.Response(503)

    issue = FakeIssue()
    issue.handler = everything_fails
    _call(issue, {"issue_id": 42, "body": "CI is green."})

    assert len(seen) <= MAX_REQUESTS


def test_the_cycle_waits_as_long_as_the_server_asked():
    # A Retry-After seen by the transport has to reach the layer above it,
    # or the outer loop sleeps a flat second while the server said sixty.
    slept = []
    issue = FakeIssue(post_outcomes=[httpx.Response(429, headers={"retry-after": "30"})] * 20)

    def build(token):
        return ResilientClient(
            "https://api.github.com", token, transport=httpx.MockTransport(issue.handler),
        )

    with patch("tools.comment_on_ticket._build_client", build), \
         patch("tools.comment_on_ticket.time.sleep", side_effect=slept.append):
        _call_result = comment_on_ticket.handler({"issue_id": 42, "body": "CI is green."})

    assert 30.0 in slept, "the server's own number never reached the cycle loop"
