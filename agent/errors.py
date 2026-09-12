# agent/errors.py
#
# One taxonomy for every tool failure, HTTP or local. Before this, each tool
# invented its own vocabulary (network_error:, embedding_service_unavailable:,
# github_error_403, path_denied), which meant nothing could ask the one
# question the retry and recovery logic actually needs: is this worth trying
# again? ErrorClass answers it once, for all of them.
#
# The wire format stays a string, "<class>: <detail>", so ToolResult.error_code
# does not change shape — what changes is that the part before the colon now
# comes from a closed set. Local tools still emit their own legacy codes;
# classify() maps those too, so retryability works today and each tool
# migrates when it is next touched rather than in one repo-wide refactor.
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorClass(str, Enum):
    AUTH = "auth"                  # no credentials, or they were rejected
    DENIED = "denied"              # authenticated, but this is not allowed — a policy refusal
    NOT_FOUND = "not_found"
    VALIDATION = "validation"      # the request itself is malformed
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"    # the other side is down or unreachable
    TIMEOUT = "timeout"
    INTERNAL = "internal"          # a bug on our side


# The only classes worth retrying. DENIED is deliberately absent: a policy
# refusal is a correct, final answer, not a transient failure — retrying one
# is how a guard gets worn down into a suggestion.
RETRYABLE = frozenset({ErrorClass.RATE_LIMIT, ErrorClass.UNAVAILABLE, ErrorClass.TIMEOUT})


@dataclass(frozen=True)
class ToolError:
    """A classified failure. str() gives the ToolResult.error_code wire form."""

    error_class: ErrorClass
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.error_class.value}: {self.detail}" if self.detail else self.error_class.value

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRYABLE


def from_status(status_code: int) -> ErrorClass:
    """Map an HTTP status onto the taxonomy.

    403 is DENIED, not RATE_LIMIT, even though GitHub also uses it for
    secondary rate limits — the two are only distinguishable by a Retry-After
    header, which is the caller's job to check before calling this.
    """
    if status_code == 401:
        return ErrorClass.AUTH
    if status_code == 403:
        return ErrorClass.DENIED
    if status_code == 404:
        return ErrorClass.NOT_FOUND
    if status_code == 429:
        return ErrorClass.RATE_LIMIT
    if 500 <= status_code < 600:
        return ErrorClass.UNAVAILABLE
    if 400 <= status_code < 500:
        return ErrorClass.VALIDATION
    return ErrorClass.INTERNAL


# Legacy per-tool codes, mapped so retryability works before the tools
# themselves migrate. Matched on the part before ":" — every code that carries
# detail spells it "code: detail".
_LEGACY_CLASSES = {
    # tools/bash.py
    "empty_command": ErrorClass.VALIDATION,
    "parse_error": ErrorClass.VALIDATION,
    "empty_pipeline_stage": ErrorClass.VALIDATION,
    "too_many_pipeline_stages": ErrorClass.VALIDATION,
    "shell_operator_rejected": ErrorClass.DENIED,
    "executable_not_allowed": ErrorClass.DENIED,
    "argument_escapes_workspace": ErrorClass.DENIED,
    # tools/edit_file.py
    "missing_path": ErrorClass.VALIDATION,
    "invalid_insert_line": ErrorClass.VALIDATION,
    "unknown_command": ErrorClass.VALIDATION,
    "ambiguous_match": ErrorClass.VALIDATION,
    "string_not_found": ErrorClass.NOT_FOUND,
    "not_found": ErrorClass.NOT_FOUND,
    "path_escapes_workspace": ErrorClass.DENIED,
    "path_denied": ErrorClass.DENIED,
    "auth_symbol_touched": ErrorClass.DENIED,
    # tools/fetch_ticket.py
    "missing_issue_id": ErrorClass.VALIDATION,
    "empty_body": ErrorClass.VALIDATION,
    "issue_not_found": ErrorClass.NOT_FOUND,
    "github_token_not_set": ErrorClass.AUTH,
    "network_error": ErrorClass.UNAVAILABLE,
    # tools/search_kb.py
    "missing_query": ErrorClass.VALIDATION,
    "invalid_filters": ErrorClass.VALIDATION,
    "embedding_service_unavailable": ErrorClass.UNAVAILABLE,
    # agent/runtime.py's dispatch loop
    "unknown_tool": ErrorClass.VALIDATION,
    "invalid_args": ErrorClass.VALIDATION,
    "side_effect_not_allowed": ErrorClass.DENIED,
    "too_many_parallel_calls": ErrorClass.DENIED,
    "handler_error": ErrorClass.INTERNAL,
}

# Deliberately unmapped: bash's "exit_<n>". A non-zero exit from an
# allowlisted read-only command is usually a normal negative result (grep
# matched nothing), not a failure of the tool — classifying it either way
# would assert something we have not decided. It falls to INTERNAL, which is
# not retryable, so the safe outcome holds until we decide.


def classify(error_code: str | None) -> ErrorClass:
    """The class of a ToolResult.error_code, new-style or legacy.

    An unrecognised code is INTERNAL, and therefore never retryable: a code
    nobody has classified must not silently become one the agent retries.
    """
    if not error_code:
        return ErrorClass.INTERNAL
    head = error_code.split(":", 1)[0].strip()
    try:
        return ErrorClass(head)
    except ValueError:
        return _LEGACY_CLASSES.get(head, ErrorClass.INTERNAL)


def is_retryable(error_code: str | None) -> bool:
    return classify(error_code) in RETRYABLE
