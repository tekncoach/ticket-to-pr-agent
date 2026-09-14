# agent/tickets.py
#
# The trigger side of SPEC.md: which issues the agent may work, and what it is
# told when it works one.
#
# Separate from tools/fetch_ticket.py on purpose. That is a tool the model
# calls once a run has started; this decides whether a run starts at all. The
# label check in particular must not be something the agent can reason its way
# around — it is the contract, checked before the model sees anything.
from __future__ import annotations

import os

from agent.config import REPO
from agent.errors import ErrorClass, ToolError
from agent.runtime import ToolResult
from agent.secrets_redaction import redact_secrets
from tools.http_client import ResilientClient

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# SPEC.md's Trigger section: "That label is the contract — no label, no run."
# It was stated there and enforced nowhere until this file.
READY_LABEL = "agent:ready"
MAX_QUEUE = 20


def _build_client(token: str) -> ResilientClient:
    # A seam, so tests can answer with a MockTransport instead of a network.
    return ResilientClient(GITHUB_API, token, timeout=15)


def _fail(error_class: ErrorClass, detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(error_class, detail)))


def _issue_summary(issue: dict) -> dict:
    """What the queue shows. Redacted like anything else GitHub hands back —
    an issue is written by anyone, and the queue is rendered in a browser."""
    labels = [label.get("name") for label in issue.get("labels") or []]
    return {
        "number": issue.get("number"),
        "title": redact_secrets(issue.get("title") or ""),
        "url": issue.get("html_url"),
        "labels": labels,
        # Carried per row rather than used as a filter, so the queue shows the
        # whole backlog and says which part of it the agent may touch. A queue
        # filtered down to the allowed rows hides the contract; a queue that
        # marks them demonstrates it, and clicking a row without the label is
        # how you watch check_ready refuse.
        "ready": READY_LABEL in labels,
    }


def list_issues(ready_only: bool = False) -> ToolResult:
    """Open issues, each flagged with whether the agent may work it."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return _fail(ErrorClass.AUTH, "GITHUB_TOKEN is not set")

    params = {"state": "open", "per_page": MAX_QUEUE}
    if ready_only:
        params["labels"] = READY_LABEL

    with _build_client(token) as client:
        result = client.request(
            "GET", f"/repos/{REPO}/issues", headers=GITHUB_HEADERS, params=params,
        )

    if not result.ok:
        return result
    issues = result.data if isinstance(result.data, list) else []
    # GitHub's issues endpoint also returns pull requests; a PR is not a ticket.
    return ToolResult(ok=True, data=[
        _issue_summary(i) for i in issues if "pull_request" not in i
    ])


def check_ready(issue_id: int) -> ToolResult:
    """Whether this issue may be worked. Refuses rather than assuming."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return _fail(ErrorClass.AUTH, "GITHUB_TOKEN is not set")

    with _build_client(token) as client:
        result = client.request(
            "GET", f"/repos/{REPO}/issues/{issue_id}", headers=GITHUB_HEADERS,
        )

    if not result.ok:
        return result
    issue = result.data or {}
    labels = [label.get("name") for label in issue.get("labels") or []]
    if READY_LABEL not in labels:
        # DENIED, not NOT_FOUND: the issue exists and the answer is no. A
        # human decides an issue is agent-treatable by labelling it, and
        # nothing here may decide otherwise.
        return _fail(
            ErrorClass.DENIED,
            f"issue #{issue_id} does not carry {READY_LABEL} — "
            f"a human labels an issue before the agent may work it",
        )
    return ToolResult(ok=True, data=_issue_summary(issue))


def task_prompt(issue_id: int) -> str:
    """What the agent is told when handed a ticket.

    SPEC.md's happy path, in the order it names: read the ticket, consult the
    knowledge base before writing code, edit, run the tests until green, and
    only then propose. The last sentence is the one that matters most — it is
    the difference between an agent that reports failure and one that opens a
    pull request nobody asked for.
    """
    return (
        f"Work GitHub issue #{issue_id} on {REPO}.\n"
        f"1. Read it with fetch_ticket.\n"
        f"2. Before writing any code, call search_kb for the conventions that "
        f"apply (commit style, test structure, review expectations) and cite "
        f"what you use.\n"
        f"3. Locate the relevant code with bash, then make the change with "
        f"str_replace_based_edit_tool.\n"
        f"4. Run run_tests and read 'green'. If it is false, fix what the "
        f"failures name and run it again.\n"
        f"5. Only once the suite is green, call open_pr with a title and a "
        f"description of what changed and why.\n"
        f"If you cannot get the suite green, do NOT open a pull request. "
        f"Call comment_on_ticket instead, saying what you tried and what "
        f"stopped you."
    )
