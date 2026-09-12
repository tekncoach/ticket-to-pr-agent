# tools/comment_on_ticket.py
#
# The first tool that writes to a system outside this machine: it posts the
# run's outcome back on the issue. SPEC.md's step 8, and the only report a
# failed run produces at all ("could not resolve after N turns").
#
# GitHub has no idempotency mechanism on this endpoint — checked against the
# REST documentation for POST /repos/{owner}/{repo}/issues/{n}/comments, which
# accepts no Idempotency-Key and does not deduplicate identical bodies. So
# sending that header, as the usual resilient-client shape does, is a no-op
# here: it is a Stripe idiom, not an HTTP one. Retrying a POST because we
# attached a key would produce exactly the double comment it looks like it
# prevents.
#
# Idempotency is therefore enforced on our side, and the shape matters:
#
#   1. The key is embedded in the comment body as an HTML comment, invisible
#      when GitHub renders it. That makes the posted comment itself the record
#      of what was posted — no local state to keep in sync with the remote.
#   2. Every attempt reads the issue's comments first and stops if the key is
#      already there — and a read that fails is "unknown", never "absent".
#      Collapsing those two is what lets a flaky read produce duplicates.
#   3. The retry loop wraps the whole read-then-write cycle, not the POST. The
#      transport is told NOT to retry (no key passed to it), so the POST is
#      sent at most once per cycle.
#
# Point 3 is what makes it actually safe: a POST that times out after GitHub
# already accepted it reports failure, and the next cycle's read finds the
# marker and stops. A transport-level retry cannot do that — it would repost
# blind.
from __future__ import annotations

import os
import time

from agent.config import REPO
from agent.errors import ErrorClass, ToolError, is_retryable, parse
from agent.runtime import Tool, ToolResult
from agent.secrets_redaction import redact_secrets
from tools.http_client import (
    ResilientClient,
    backoff_delay,
    idempotency_key,
    retry_after_seconds,
)

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Two retry layers sit on top of each other here, and the composition is
# deliberate rather than accidental — spelling it out because 3 cycles over a
# client that retries 4 times reads like 12 attempts against a rate limit.
#
#   Transport (ResilientClient): retries the READ, up to READ_ATTEMPTS. It
#     never retries the POST — no idempotency key is passed, precisely so it
#     cannot repost blind.
#   Cycle (here): re-runs the whole read-then-write, because that is the only
#     thing that can notice a write which landed and lost its response.
#
# The read's budget is cut to 2 inside the cycle for exactly this reason: the
# cycle already provides the outer retry, so the default 4 would multiply
# rather than add. Worst case is now READ_ATTEMPTS x MAX_CYCLES reads plus
# MAX_CYCLES writes — 9 requests, not 15 — and a test pins that number.
MAX_CYCLES = 3
READ_ATTEMPTS = 2
MAX_REQUESTS = MAX_CYCLES * (READ_ATTEMPTS + 1)
# One page is enough to find a marker we posted ourselves, which is always
# among the most recent comments. A busy issue could in principle push it past
# 100 — the cost of missing it is one duplicate comment, not a wrong action.
COMMENTS_PER_PAGE = 100


def _marker(key: str) -> str:
    return f"<!-- agent-idempotency: {key} -->"


def _build_client(token: str) -> ResilientClient:
    # A seam, so tests can answer with a MockTransport instead of a network.
    return ResilientClient(GITHUB_API, token, timeout=10, max_attempts=READ_ATTEMPTS)


def _shadow_mode() -> bool:
    # Read at call time, not import time: tests and the service both change it.
    return os.environ.get("SHADOW_MODE", "true").lower() == "true"


def _find_marked_comment(
    client: ResilientClient, issue_id: int, key: str,
) -> tuple[dict | None, bool]:
    """(the comment carrying this key or None, whether the read succeeded).

    The second value is not a detail. "No marker found" and "could not look"
    are different answers, and collapsing them into None is what lets a flaky
    read turn into a duplicate comment.
    """
    result = client.request(
        "GET", f"/repos/{REPO}/issues/{issue_id}/comments",
        headers=GITHUB_HEADERS, params={"per_page": COMMENTS_PER_PAGE},
    )
    if not result.ok or not isinstance(result.data, list):
        return None, False
    return next((c for c in result.data if _marker(key) in (c.get("body") or "")), None), True


def _handler(arguments: dict) -> ToolResult:
    issue_id = arguments.get("issue_id")
    if not issue_id:
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "missing issue_id")))

    body = (arguments.get("body") or "").strip()
    if not body:
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "missing body")))

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.AUTH, "GITHUB_TOKEN is not set")))

    # The intent, not the attempt: the same comment on the same issue hashes to
    # the same key however many times the agent asks for it.
    key = idempotency_key(REPO, "comment_on_ticket", {"issue": issue_id, "body": body})
    marked_body = f"{body}\n\n{_marker(key)}"
    target = f"{REPO}#{issue_id}"

    # Dry run does everything except the write, including the duplicate check,
    # so the receipt reflects what would actually happen rather than what the
    # caller hopes. SHADOW_MODE forces it: the runtime's write gate already
    # blocks side-effect tools in shadow mode, and this is the second lock, so
    # that opening the gate cannot on its own start posting to a real repo.
    dry_run = bool(arguments.get("dry_run")) or _shadow_mode()

    # The last real failure, kept as a ToolError so the class survives the
    # loop. Wrapping an already-stringified error_code in a ToolError whose
    # declared class is INTERNAL happens to work while only .detail is read,
    # and lies the moment anyone reads the class — which is the one thing the
    # taxonomy exists to be trusted for.
    error = ToolError(ErrorClass.INTERNAL, "no attempt was made")
    posted_once = False
    with _build_client(token) as client:
        for cycle in range(MAX_CYCLES):
            existing, read_ok = _find_marked_comment(client, issue_id, key)
            if existing is not None:
                return ToolResult(ok=True, data=(
                    f"already commented on {target} "
                    f"(comment {existing.get('id')}) — no duplicate posted: {existing.get('html_url')}"
                ))

            if dry_run:
                reason = "SHADOW_MODE" if _shadow_mode() else "dry_run"
                return ToolResult(ok=True, data=(
                    f"would comment on {target} ({reason}, nothing posted): {body}"
                ))

            # Only write on positive knowledge that no marker is there. Once a
            # POST has been sent, a read we could not complete means "unknown",
            # and unknown must not become "post it again" — the previous one may
            # have landed and lost its response. Stopping here can leave the
            # comment unconfirmed; posting again duplicates it for certain.
            if posted_once and not read_ok:
                return ToolResult(ok=False, error_code=str(ToolError(
                    ErrorClass.UNAVAILABLE,
                    f"a comment was sent to {target} but could not be confirmed; "
                    "not reposting, check the issue",
                )))

            # No idempotency_key passed on purpose: GitHub ignores the header,
            # so a transport retry here would repost. This cycle's read is the
            # real guard, and it runs again on the next pass.
            posted_once = True
            result = client.request(
                "POST", f"/repos/{REPO}/issues/{issue_id}/comments",
                headers=GITHUB_HEADERS, json={"body": marked_body},
            )
            if result.ok:
                comment = result.data or {}
                return ToolResult(ok=True, data=(
                    f"commented on {target} (comment {comment.get('id')}): {comment.get('html_url')}"
                ))

            error = parse(result.error_code)
            if not is_retryable(result.error_code):
                return ToolResult(
                    ok=False,
                    error_code=result.error_code,
                    data=redact_secrets(result.data) if isinstance(result.data, str) else None,
                )
            if cycle < MAX_CYCLES - 1:
                # The same jittered backoff the transport uses, not a flat
                # second: two layers sleeping in lockstep is how a recovering
                # service gets hit by a wave of identical callers.
                time.sleep(backoff_delay(cycle, retry_after_seconds(result)))

    # Rebuilt from the class rather than by appending to the previous string:
    # the transport already wrote "after N attempts" into it, and stacking a
    # second suffix produces "after 4 attempts after 3 cycles".
    return ToolResult(ok=False, error_code=str(ToolError(
        error.error_class, f"{error.detail} — gave up after {MAX_CYCLES} cycles")))


comment_on_ticket = Tool(
    name="comment_on_ticket",
    description=(
        f"Post a comment reporting the run's outcome on an Issue in {REPO}. "
        "Posting the same body on the same issue twice is a no-op — the second "
        "call reports the existing comment instead of duplicating it. Returns a "
        "receipt naming the issue and the comment's URL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "issue_id": {"type": "integer", "description": "The GitHub Issue number to comment on."},
            "body": {"type": "string", "description": "The comment text, in Markdown."},
            "dry_run": {
                "type": "boolean",
                "description": "Report what would be posted without posting it.",
            },
        },
        "required": ["issue_id", "body"],
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=True,
)
