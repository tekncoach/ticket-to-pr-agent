# tools/fetch_ticket.py
#
# Reads one Issue's title + body as the ticket spec. Whether the issue carries
# `agent:ready` is the trigger's job (SPEC.md's Trigger section), not this
# tool's — fetch_ticket just reads the issue it is given.
#
# Goes through tools/http_client.py rather than calling httpx itself, so it
# inherits retry-with-backoff, Retry-After, and the shared error taxonomy —
# this was the one live integration with no retry at all.
#
# Everything GitHub returns is redacted (agent.secrets_redaction) before it
# leaves this tool, error bodies included: an Issue is written by anyone, and
# a pasted secret in a repro example is exactly the shape of the risk. See
# docs/SECRETS-REDACTION.md.
from __future__ import annotations

import os

from agent.config import REPO
from agent.errors import ErrorClass, ToolError
from agent.runtime import Tool, ToolResult
from agent.secrets_redaction import redact_secrets
from tools.http_client import ResilientClient

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _build_client(token: str) -> ResilientClient:
    # A seam, so tests can answer with a MockTransport instead of a network.
    return ResilientClient(GITHUB_API, token, timeout=10)


def _handler(arguments: dict) -> ToolResult:
    issue_id = arguments.get("issue_id")
    if not issue_id:
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "missing issue_id")))

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.AUTH, "GITHUB_TOKEN is not set")))

    # The client is closed per call, but the retry attempts inside one call
    # share its connection pool — which is where reuse actually pays.
    with _build_client(token) as client:
        result = client.request("GET", f"/repos/{REPO}/issues/{issue_id}", headers=GITHUB_HEADERS)

    if not result.ok:
        # Already classified and already retried where retrying was safe.
        # The body is GitHub's, so it gets redacted like any other.
        return ToolResult(
            ok=False,
            error_code=result.error_code,
            data=redact_secrets(result.data) if isinstance(result.data, str) else None,
        )

    data = result.data or {}
    body = (data.get("body") or "").strip()
    if not body:
        return ToolResult(
            ok=False,
            error_code=str(ToolError(ErrorClass.VALIDATION, f"issue #{issue_id} has an empty body")),
        )

    return ToolResult(ok=True, data={
        "title": redact_secrets(data.get("title", "")),
        "body": redact_secrets(body),
    })


fetch_ticket = Tool(
    name="fetch_ticket",
    description=(
        "Fetch a GitHub Issue's title and body from "
        f"{REPO}, as the ticket spec to implement."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "issue_id": {
                "type": "integer",
                "description": "The GitHub Issue number to fetch.",
            }
        },
        "required": ["issue_id"],
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=False,
)
