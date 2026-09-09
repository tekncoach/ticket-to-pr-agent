# tools/fetch_ticket.py
#
# Hand-written GitHub REST call — SPEC.md's POC default (PyGithub is the
# named production upgrade, once the tool must survive rate limits and
# structured error handling in front of a customer; not needed yet).
#
# Reads one Issue's title + body as the ticket spec. Whether the issue
# actually carries `agent:ready` is the trigger's job (SPEC.md's Trigger
# section), not this tool's — fetch_ticket just reads the issue it's given.
from __future__ import annotations

import os

import httpx

from agent.config import REPO
from agent.runtime import Tool, ToolResult

GITHUB_API = "https://api.github.com"


def _handler(arguments: dict) -> ToolResult:
    issue_id = arguments.get("issue_id")
    if not issue_id:
        return ToolResult(ok=False, error_code="missing_issue_id")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return ToolResult(ok=False, error_code="github_token_not_set")

    try:
        resp = httpx.get(
            f"{GITHUB_API}/repos/{REPO}/issues/{issue_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
    except httpx.RequestError as exc:
        return ToolResult(ok=False, error_code=f"network_error: {exc}")

    if resp.status_code == 404:
        return ToolResult(ok=False, error_code="issue_not_found")
    if resp.status_code != 200:
        return ToolResult(ok=False, error_code=f"github_error_{resp.status_code}")

    data = resp.json()
    body = (data.get("body") or "").strip()
    if not body:
        return ToolResult(ok=False, error_code="empty_body")

    return ToolResult(ok=True, data={"title": data.get("title", ""), "body": body})


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
