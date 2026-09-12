# tools/http_client.py
#
# One HTTP client for every external integration, so retry policy and error
# classification live in one place instead of being re-decided per tool.
#
# Four things the obvious version of this gets wrong, each fixed here and
# each with its own regression test:
#
# 1. Retrying a write duplicates it. A retried POST that already created an
#    issue creates a second one. Retries are therefore restricted to
#    idempotent methods, unless the caller supplies an idempotency key.
#    idempotency_key() is not a helper sitting next to request(); passing it
#    is what unlocks the retry.
#    ⚠ Passing it only makes the write safe if the SERVER honours the header.
#    GitHub does not — see tools/comment_on_ticket.py, which enforces
#    idempotency itself and deliberately withholds the key so this layer
#    cannot repost.
# 2. Reporting the wrong error at the end. Looping and then returning a fixed
#    code means four 500s get reported as a rate limit. The last real error is
#    what comes back.
# 3. Ignoring Retry-After. The server says how long to wait; guessing 0.5s
#    when it said 60 is how a rate limit becomes a ban.
# 4. Backoff with no jitter. Callers that fail together retry together, and
#    hit the recovering service as one wave.
from __future__ import annotations

import hashlib
import json
import random
import time

import httpx

from agent.errors import ErrorClass, ToolError, from_status
from agent.runtime import ToolResult

MAX_ATTEMPTS = 4
BASE_DELAY_S = 0.5
MAX_DELAY_S = 60.0

# Methods safe to repeat by definition (RFC 9110). Anything else needs an
# idempotency key before it may be retried.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def retry_after_seconds(source: httpx.Response | ToolResult | None) -> float | None:
    """Retry-After from a response, or from a ToolResult that carried one back.

    The cycle loop in tools/comment_on_ticket.py only sees the ToolResult, and
    a server that said how long to wait should be obeyed at both layers.
    """
    if isinstance(source, ToolResult):
        return source.retry_after
    if source is None:
        return None
    return _response_retry_after(source)


def _response_retry_after(response: httpx.Response) -> float | None:
    """Retry-After in seconds, capped. None when absent or not a number —
    the HTTP-date form is unused by the APIs we call, so it is not parsed."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return min(float(raw), MAX_DELAY_S)
    except ValueError:
        return None


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """The server's own number wins when it gave one. Otherwise exponential
    with equal jitter: half the delay fixed so we always back off, half random
    so simultaneous callers spread out instead of retrying in lockstep."""
    if retry_after is not None:
        return retry_after
    delay = min(BASE_DELAY_S * (2 ** attempt), MAX_DELAY_S)
    return delay / 2 + random.uniform(0, delay / 2)


_backoff_delay = backoff_delay  # the private spelling the tests were written against


class ResilientClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 15.0,
        max_attempts: int = MAX_ATTEMPTS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        # One client for the object's life: connection pooling only works if
        # the pool outlives the request. transport is the seam tests use to
        # answer without a network.
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ResilientClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        idempotency_key: str | None = None,
        **kwargs: object,
    ) -> ToolResult:
        method = method.upper()
        may_retry = method in IDEMPOTENT_METHODS or idempotency_key is not None

        headers = dict(kwargs.pop("headers", None) or {})
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        url = f"{self.base_url}{path}"
        error = ToolError(ErrorClass.INTERNAL, "no attempt was made")
        body: str | None = None
        retry_after: float | None = None

        for attempt in range(self.max_attempts):
            retry_after = None
            try:
                response = self._client.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                error, body = ToolError(ErrorClass.TIMEOUT, str(exc) or "request timed out"), None
            except httpx.HTTPError as exc:
                # Connection reset, DNS failure, refused connection: transient
                # by nature, so retryable — the template treated these as final.
                error, body = ToolError(ErrorClass.UNAVAILABLE, str(exc)), None
            else:
                if response.status_code < 400:
                    return ToolResult(ok=True, data=response.json() if response.content else None)
                error_class = from_status(response.status_code)
                retry_after = _response_retry_after(response)
                # GitHub signals a secondary rate limit as 403 + Retry-After.
                # That header is the only thing separating it from a plain
                # permissions refusal, which must never be retried.
                if error_class is ErrorClass.DENIED and retry_after is not None:
                    error_class = ErrorClass.RATE_LIMIT
                error = ToolError(error_class, f"HTTP {response.status_code}")
                body = response.text[:500] or None

            if not error.retryable:
                break
            if not may_retry:
                # Say why it stopped rather than looking like a hard failure:
                # this one was retryable, we chose not to repeat a write.
                error = ToolError(
                    error.error_class,
                    f"{error.detail} (not retried: {method} without an idempotency key)",
                )
                break
            if attempt == self.max_attempts - 1:
                error = ToolError(error.error_class, f"{error.detail} after {self.max_attempts} attempts")
                break
            time.sleep(_backoff_delay(attempt, retry_after))

        return ToolResult(ok=False, error_code=str(error), data=body, retry_after=retry_after)


def idempotency_key(actor: str, action: str, payload: dict) -> str:
    """A stable key for one intended write. The same intent hashes to the same
    key, so a retry is recognisable as the same request rather than a new one.

    actor, not user_id: this agent runs as a service account, so there is no
    user to key on — callers pass the target repo. Naming the parameter for an
    identity we do not have would promise a scoping we cannot deliver.
    """
    raw = json.dumps({"u": actor, "a": action, "p": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
