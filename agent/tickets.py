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

from agent.config import REPO, WORKSPACE
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
        # GitHub's issues endpoint also returns pull requests; a PR is not a
        # ticket. But a PR the agent already opened for one IS worth showing
        # next to it — the queue is where you look to find out what happened.
        prs = client.request(
            "GET", f"/repos/{REPO}/pulls", headers=GITHUB_HEADERS,
            params={"state": "all", "per_page": MAX_QUEUE},
        )

    # Imported here rather than at module scope: tools/open_pr.py imports
    # check_ready from this module, and the branch name is the only thing
    # needed the other way. A lazy import beats duplicating the naming rule,
    # which is the one string linking an issue to its pull request.
    from tools.open_pr import branch_for

    by_branch = {}
    if prs.ok and isinstance(prs.data, list):
        by_branch = {(p.get("head") or {}).get("ref"): p for p in prs.data}

    rows = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        summary = _issue_summary(issue)
        pr = by_branch.get(branch_for(summary["number"]))
        summary["pr"] = {
            "number": pr.get("number"), "url": pr.get("html_url"),
            "state": "draft" if pr.get("draft") else pr.get("state"),
            # The CI result, linked. SPEC.md calls CI the oracle — "the agent's
            # job is to converge to green CI" — and until now the queue showed
            # that a PR existed while staying silent on the only question that
            # decides whether it was any good. A green badge is a claim; a link
            # to the run that produced it is evidence.
            "ci": _ci_for(token, (pr.get("head") or {}).get("sha")),
        } if pr else None
        rows.append(summary)
    return ToolResult(ok=True, data=rows)


def _ci_for(token: str, sha: str | None) -> dict | None:
    """The CI run for a commit: its conclusion and a link to it.

    None when there is no run rather than a fabricated "pending" — a workflow
    that never fired and one still running are different facts, and only one
    of them is worth waiting for.
    """
    if not sha:
        return None
    with _build_client(token) as client:
        result = client.request(
            "GET", f"/repos/{REPO}/actions/runs",
            headers=GITHUB_HEADERS, params={"head_sha": sha, "per_page": 10},
        )
    if not result.ok or not isinstance(result.data, dict):
        return None
    runs = [r for r in result.data.get("workflow_runs") or []
            if r.get("name", "").upper() == "CI"] or (result.data.get("workflow_runs") or [])
    if not runs:
        return None
    run = runs[0]
    return {
        # conclusion is null while a run is in progress; status carries that.
        "conclusion": run.get("conclusion") or run.get("status"),
        "url": run.get("html_url"),
        "name": run.get("name"),
    }


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
    if issue.get("state") == "closed":
        return _fail(
            ErrorClass.DENIED,
            f"issue #{issue_id} is closed — someone decided it was done or "
            f"not wanted while this was running",
        )
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
        f"You are already inside a checkout of that repository: bash runs "
        f"there and every path is relative to its root, so `ls` and "
        f"`view app.py` work directly. Never search from / — you are in the "
        f"repo already, at {WORKSPACE}. Use paths relative to it — ./app.py, "
        f"not /repo/app.py. bash allows grep, cat, find, ls, head, tail, wc, "
        f"pwd, sed, awk and git, reading only: an in-place flag or a "
        f"writing git subcommand is refused (open_pr owns those). No "
        f"redirects and no && — a single pipe between allowed commands is the "
        f"one operator that works. Globs like tests/*.py do work. stderr is "
        f"already merged into the output, so 2>&1 is unnecessary and refused.\n"
        f"1. Read it with fetch_ticket. It names the files and the existing "
        f"patterns to follow — trust it rather than rediscovering them.\n"
        f"2. Read only what the ticket points at. The edit-then-test loop is "
        f"your discovery tool, not more reading: a first imperfect edit "
        f"followed by run_tests teaches you more about this codebase than "
        f"another view of another file, because the tests answer with facts. "
        f"Write as soon as you can name the change.\n"
        f"3. Make it with str_replace_based_edit_tool.\n"
        f"4. Run run_tests and read 'green'. If it is false, fix what the "
        f"failures name and run it again. Repeat — this is the loop.\n"
        f"5. Only once the suite is green, call open_pr with a title and a "
        f"description of what changed and why.\n"
        f"search_kb is available if you need a convention the ticket does not "
        f"state. Call it when you have a question it can answer, not as a "
        f"step to tick off — it searches an engineering-practices corpus, not "
        f"this repository, so it knows nothing about these files.\n"
        f"If you cannot get the suite green, do NOT open a pull request. "
        f"Call comment_on_ticket instead, saying what you tried and what "
        f"stopped you.\n"
        f"If you find the work is ALREADY done — the change is present and "
        f"the suite is green without you editing anything — that is also a "
        f"result, and it is not finished until it is on the ticket: call "
        f"comment_on_ticket saying so. Telling only this console leaves the "
        f"person who labelled the issue with nothing."
    )
