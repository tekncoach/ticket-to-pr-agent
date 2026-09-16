# tools/open_pr.py
#
# SPEC.md's step 6, and the end of the loop: turn the working tree the agent
# has been editing into a draft pull request.
#
# Draft, always. Shadow mode is the rollout stance (SPEC.md, Shadow/rollout):
# the agent proposes, a human reviews, and nothing merges on its own.
#
# Three things this tool has to get right, and each one has a way of going
# quietly wrong.
#
# 1. WHAT GETS COMMITTED. Never `git add -A`. tools/edit_file.py writes a
#    <file>.bak beside every file it overwrites, and the target repo does not
#    ignore those — a blanket add ships the agent's own backups as part of the
#    change. Files are enumerated from `git status --porcelain` (which already
#    excludes ignored paths) and the backups filtered out by name.
#
# 2. NOT OPENING THE SAME PR TWICE. Unlike an issue comment, GitHub does give
#    us something to check here: a pull request is uniquely identified by its
#    head branch. The branch name is derived from the issue number, so the
#    same intent always resolves to the same branch, and a lookup on that head
#    tells us whether the PR already exists. Same read-before-write shape as
#    tools/comment_on_ticket.py, with a real key instead of an embedded marker.
#
# 3. NOT LEAKING THE TOKEN. The remote is HTTPS, so pushing means putting the
#    credential in the URL. That URL is never returned, never logged, and
#    every git error is redacted before it leaves this module — a failed push
#    prints the remote it tried, and that string contains the token.
from __future__ import annotations

import os
import subprocess

from agent.config import REPO, WORKSPACE, shadow_mode
from agent.errors import ErrorClass, ToolError
from agent.tickets import check_ready
from agent.runtime import Tool, ToolResult
from agent.secrets_redaction import redact_secrets
from tools.http_client import ResilientClient

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

BASE_BRANCH = os.environ.get("TARGET_BASE_BRANCH", "main")
GIT_TIMEOUT_S = 120
# edit_file's own backups. They live next to the file they shadow, and the
# target repo has no rule excluding them.
BACKUP_SUFFIX = ".bak"
MAX_DETAIL_CHARS = 300


def _fail(error_class: ErrorClass, detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(error_class, redact_secrets(detail))))


def _build_client(token: str) -> ResilientClient:
    # A seam, so tests can answer with a MockTransport instead of a network.
    return ResilientClient(GITHUB_API, token, timeout=15)


def branch_for(issue_id: int) -> str:
    """Deterministic, so the same issue always maps to the same head branch —
    which is what makes the existing-PR lookup a real idempotency key."""
    return f"agent/issue-{issue_id}"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=WORKSPACE, capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
    )


def _changed_files() -> list[str]:
    """Paths git reports as changed, minus edit_file's backups.

    Porcelain output already omits ignored paths, so the target repo's own
    .gitignore does most of the work; the backups are the part it does not
    cover.
    """
    proc = _git("status", "--porcelain")
    if proc.returncode != 0:
        return []
    paths = []
    for line in proc.stdout.splitlines():
        path = line[3:].strip().strip('"')
        # A rename reads as "old -> new"; only the new path is stageable.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and not path.endswith(BACKUP_SUFFIX):
            paths.append(path)
    return paths


def _existing_pr(client: ResilientClient, branch: str) -> dict | None:
    owner = REPO.split("/")[0]
    result = client.request(
        "GET", f"/repos/{REPO}/pulls",
        headers=GITHUB_HEADERS,
        # state=open, not all. With "all", a pull request that was closed or
        # merged still answered "already open for this issue", so the branch
        # could never be proposed again — the one case where reopening the work
        # is exactly what should happen.
        params={"head": f"{owner}:{branch}", "state": "open", "per_page": 10},
    )
    if not result.ok or not isinstance(result.data, list) or not result.data:
        return None
    return result.data[0]


def _handler(arguments: dict) -> ToolResult:
    issue_id = arguments.get("issue_id")
    if not issue_id:
        return _fail(ErrorClass.VALIDATION, "missing issue_id")

    title = (arguments.get("title") or "").strip()
    if not title:
        return _fail(ErrorClass.VALIDATION, "missing title")

    description = (arguments.get("description") or "").strip()
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return _fail(ErrorClass.AUTH, "GITHUB_TOKEN is not set")

    files = _changed_files()
    if not files:
        # Not a failure of this tool, but there is nothing to propose. Saying
        # so plainly beats opening an empty PR.
        return _fail(ErrorClass.VALIDATION, "the working tree has no changes to open a PR for")

    # The contract, re-read immediately before the irreversible act. /v1/run
    # checks it once at the start, and a run takes minutes: a human who
    # removes the label or closes the issue mid-run has withdrawn consent, and
    # a gate only consulted at the door is not a human-in-the-loop gate.
    #
    # Deliberately NOT done in comment_on_ticket: that is how the agent
    # reports, including reporting that it stopped. Gating the report as well
    # would make withdrawal silent, which is worse than the write it prevents.
    consent = check_ready(issue_id)
    if not consent.ok:
        return ToolResult(ok=False, error_code=consent.error_code)

    branch = branch_for(issue_id)
    dry_run = bool(arguments.get("dry_run")) or shadow_mode()

    with _build_client(token) as client:
        existing = _existing_pr(client, branch)
        if existing is not None:
            return ToolResult(ok=True, data=(
                f"pull request already open for issue #{issue_id} "
                f"(#{existing.get('number')}) — no duplicate created: {existing.get('html_url')}"
            ))

        if dry_run:
            reason = "SHADOW_MODE" if shadow_mode() else "dry_run"
            return ToolResult(ok=True, data=(
                f"would open a draft PR from {branch} into {BASE_BRANCH} for issue "
                f"#{issue_id} ({reason}, nothing pushed) — {len(files)} file(s): "
                f"{', '.join(files[:10])}"
            ))

        # Labelled rather than derived from argv: the commit call starts with
        # `-c key=value` pairs, so args[0] names the flag, not the operation.
        # An error saying "git -c failed" points at nothing.
        steps = (
            ("checkout", ("checkout", "-B", branch)),
            ("add", ("add", "--", *files)),
            ("commit", ("-c", "user.name=ticket-to-pr-agent", "-c", "user.email=agent@localhost",
                        "commit", "-m", f"{title}\n\nCloses #{issue_id}")),
        )
        for name, args in steps:
            proc = _git(*args)
            if proc.returncode != 0:
                return _fail(
                    ErrorClass.INTERNAL,
                    f"git {name} failed: {(proc.stderr or proc.stdout).strip()[:MAX_DETAIL_CHARS]}",
                )

        # The credential lives in the URL for exactly this call and is never
        # returned; redact_secrets covers the error path, where git echoes the
        # remote it tried back in its own message.
        push_url = f"https://x-access-token:{token}@github.com/{REPO}.git"
        proc = _git("push", "--set-upstream", push_url, branch)
        if proc.returncode != 0:
            return _fail(
                ErrorClass.INTERNAL,
                f"git push failed: {(proc.stderr or proc.stdout).strip()[:MAX_DETAIL_CHARS]}",
            )

        # No idempotency key: GitHub honours none, and the head-branch lookup
        # above is the real guard. It runs again on the next call.
        result = client.request(
            "POST", f"/repos/{REPO}/pulls",
            headers=GITHUB_HEADERS,
            json={
                "title": title,
                "head": branch,
                "base": BASE_BRANCH,
                "body": f"{description}\n\nCloses #{issue_id}".strip(),
                "draft": True,
            },
        )

    if not result.ok:
        return ToolResult(
            ok=False,
            error_code=result.error_code,
            data=redact_secrets(result.data) if isinstance(result.data, str) else None,
        )

    pr = result.data or {}
    return ToolResult(ok=True, data=(
        f"opened draft PR #{pr.get('number')} for issue #{issue_id} "
        f"from {branch} — {len(files)} file(s) changed: {pr.get('html_url')}"
    ))


open_pr = Tool(
    name="open_pr",
    description=(
        f"Open a draft pull request on {REPO} from the changes currently in "
        "the working tree, for the issue being worked on. Always a draft — a "
        "human reviews before anything merges. Calling it twice for the same "
        "issue reports the existing pull request instead of creating a second "
        "one. Returns a receipt naming the PR number and its URL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "issue_id": {"type": "integer", "description": "The Issue this change resolves."},
            "title": {"type": "string", "description": "Pull request title."},
            "description": {"type": "string", "description": "What changed and why, in Markdown."},
            "dry_run": {
                "type": "boolean",
                "description": "Report what would be pushed without pushing it.",
            },
        },
        "required": ["issue_id", "title"],
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=True,
)
