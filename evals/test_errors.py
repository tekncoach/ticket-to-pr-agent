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
    # DENIED covers path_denied, auth_symbol_touched, shell_operator_rejected.
    # Retrying a refusal is how a guard gets worn down into a suggestion.
    assert not is_retryable("denied: crypto.py")
    assert not is_retryable("path_denied")
    assert not is_retryable("auth_symbol_touched: get_session_user")


def test_unknown_code_is_internal_and_not_retryable():
    assert classify("something_nobody_mapped") == ErrorClass.INTERNAL
    assert not is_retryable("something_nobody_mapped")


def test_missing_code_is_internal():
    assert classify(None) == ErrorClass.INTERNAL
    assert classify("") == ErrorClass.INTERNAL


@pytest.mark.parametrize("code, expected", [
    ("embedding_service_unavailable: 503", ErrorClass.UNAVAILABLE),
    ("string_not_found", ErrorClass.NOT_FOUND),
    ("ambiguous_match", ErrorClass.VALIDATION),
    ("invalid_args: 'query' is a required property", ErrorClass.VALIDATION),
    ("side_effect_not_allowed", ErrorClass.DENIED),
    ("handler_error: KeyError", ErrorClass.INTERNAL),
])
def test_legacy_tool_codes_still_classify(code, expected):
    # The tools have not migrated yet; retryability has to work on their
    # current codes in the meantime, detail suffix and all.
    assert classify(code) == expected


def test_bash_exit_code_stays_unclassified_and_safe():
    # Deliberately unmapped — a non-zero exit from a read-only command is
    # usually a normal negative result (grep matched nothing), and asserting
    # a class for it would decide something we have not decided.
    assert classify("exit_1") == ErrorClass.INTERNAL
    assert not is_retryable("exit_1")


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
