# agent/errors.py
#
# One taxonomy for every tool failure, HTTP or local. Before this, each tool
# invented its own vocabulary (network_error:, embedding_service_unavailable:,
# github_error_403, path_denied), which meant nothing could ask the one
# question the retry and recovery logic actually needs: is this worth trying
# again? ErrorClass answers it once, for all of them.
#
# The wire format is a string, "<class>: <detail>", so ToolResult.error_code
# keeps its shape — what changed is that the part before the colon comes from
# a closed set. Every tool emits it; nothing needs a translation table.
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


def classify(error_code: str | None) -> ErrorClass:
    """The class of a ToolResult.error_code.

    An unrecognised code is INTERNAL, and therefore never retryable: a code
    nobody has classified must not silently become one the agent retries.
    That is the safe default for a tool added later whose author forgets this
    file exists.
    """
    if not error_code:
        return ErrorClass.INTERNAL
    try:
        return ErrorClass(error_code.split(":", 1)[0].strip())
    except ValueError:
        return ErrorClass.INTERNAL


def is_retryable(error_code: str | None) -> bool:
    return classify(error_code) in RETRYABLE
