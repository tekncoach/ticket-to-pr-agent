"""Unit tests for the shared error taxonomy. Hermetic — no network, no key.

The property that matters most here is the safe default: an error code nobody
has classified must never come back retryable, or a new tool's unknown failure
silently gains an infinite retry loop.
"""
import pytest

from agent.errors import (
    RETRYABLE,
    ErrorClass,
    ToolError,
    classify,
    from_status,
    is_retryable,
    parse,
)


@pytest.mark.parametrize("status, expected", [
    (401, ErrorClass.AUTH),
    (403, ErrorClass.DENIED),
    (404, ErrorClass.NOT_FOUND),
    (422, ErrorClass.VALIDATION),
    (400, ErrorClass.VALIDATION),
    (429, ErrorClass.RATE_LIMIT),
    (500, ErrorClass.UNAVAILABLE),
    (503, ErrorClass.UNAVAILABLE),
    (504, ErrorClass.UNAVAILABLE),
])
def test_http_status_maps_to_its_class(status, expected):
    assert from_status(status) == expected


def test_only_transient_classes_are_retryable():
    assert RETRYABLE == {ErrorClass.RATE_LIMIT, ErrorClass.UNAVAILABLE, ErrorClass.TIMEOUT}


def test_a_policy_refusal_is_never_retryable():
    # DENIED covers every guard in bash, edit_file and the dispatch loop.
    # Retrying a refusal is how a guard gets worn down into a suggestion.
    assert not is_retryable("denied: path is out of scope: crypto.py")
    assert not is_retryable("denied: auth symbol touched: get_session_user")
    assert not is_retryable("denied: shell operator rejected")


def test_unknown_code_is_internal_and_not_retryable():
    assert classify("something_nobody_mapped") == ErrorClass.INTERNAL
    assert not is_retryable("something_nobody_mapped")


def test_missing_code_is_internal():
    assert classify(None) == ErrorClass.INTERNAL
    assert classify("") == ErrorClass.INTERNAL


def test_tool_error_string_round_trips_through_classify():
    # The invariant the whole taxonomy rests on: what a tool writes into
    # error_code is what classify() can read back out of it.
    for error_class in ErrorClass:
        err = ToolError(error_class, "some detail")
        assert classify(str(err)) == error_class
        assert classify(str(ToolError(error_class))) == error_class


def test_tool_error_wire_form():
    assert str(ToolError(ErrorClass.RATE_LIMIT, "retry after 60s")) == "rate_limit: retry after 60s"
    assert str(ToolError(ErrorClass.AUTH)) == "auth"


def test_tool_error_exposes_its_own_retryability():
    assert ToolError(ErrorClass.RATE_LIMIT).retryable
    assert ToolError(ErrorClass.TIMEOUT).retryable
    assert not ToolError(ErrorClass.DENIED).retryable
    assert not ToolError(ErrorClass.VALIDATION).retryable


def test_parse_round_trips_a_wire_form_code():
    # The counterpart to str(ToolError), needed by anything that catches a
    # failure and re-raises it with more context.
    for error_class in ErrorClass:
        original = ToolError(error_class, "HTTP 429 (some detail)")
        assert parse(str(original)) == original
        assert parse(str(ToolError(error_class))) == ToolError(error_class, "")


def test_parse_does_not_double_the_prefix():
    # The bug it exists to prevent: feeding a whole error_code back in as a
    # detail produced "rate_limit: rate_limit: HTTP 429".
    reparsed = parse("rate_limit: HTTP 429")
    assert str(ToolError(reparsed.error_class, f"{reparsed.detail} — gave up")) == \
        "rate_limit: HTTP 429 — gave up"


def test_parse_keeps_an_unrecognised_code_whole_as_the_detail():
    # Nothing to strip, and dropping it would lose the only information there.
    parsed = parse("something_nobody_mapped: with detail")
    assert parsed.error_class is ErrorClass.INTERNAL
    assert parsed.detail == "something_nobody_mapped: with detail"
