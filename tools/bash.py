# tools/bash.py
#
# Anthropic-defined bash_20250124 client-side tool: schema-less on the wire,
# but Anthropic never executes it — this file is what makes it run.
#
# Three guards, per Anthropic's security note ("an allowlist of permitted
# executables, reject shell operators; a blocklist is not sufficient"):
#
# 1. Allowlisted, read-only executables only. Read-only because real policy
#    guards (write gating, arg validation, confirm=true) don't exist yet.
# 2. Never shell=True. argv form means a metacharacter that slips through
#    has no special meaning anyway. A plain pipe between allowed executables
#    (`find ... | wc -l`) is the one operator permitted, built structurally
#    with chained Popen calls rather than handed to a shell.
# 3. Every argument resolved against the workspace. cwd alone confines
#    nothing — an absolute path or `../` escapes it regardless, live-verified:
#    the agent once ran `find /some/path/outside` successfully. Uses the same
#    agent.workspace_guard.resolve_within_workspace() as tools/edit_file.py,
#    one implementation so the two can't drift.
from __future__ import annotations

import shlex
import subprocess

from agent.config import WORKSPACE
from agent.runtime import Tool, ToolResult
from agent.workspace_guard import resolve_within_workspace

ALLOWED_EXECUTABLES = {"grep", "cat", "find", "ls", "head", "tail", "wc", "pwd"}
# "|" removed on purpose: it's handled structurally below, not as a reject.
DISALLOWED_OPERATORS = ("&&", "||", ";", "`", "$(", ">", "<", "\n")
MAX_PIPELINE_STAGES = 3


def _split_pipeline(argv: list[str]) -> list[list[str]] | None:
    """Split tokens on stand-alone "|" tokens into pipeline stages.

    shlex already resolved quoting before this runs, so a `|` that was
    inside quotes (e.g. grep -E "foo|bar") survived as part of one token,
    not as its own list element — only a bare, unquoted `|` reaches here as
    a stage boundary. Returns None on an empty stage (leading/trailing/
    doubled pipe, e.g. "grep foo |").
    """
    stages: list[list[str]] = [[]]
    for tok in argv:
        if tok == "|":
            stages.append([])
        else:
            stages[-1].append(tok)
    if any(not stage for stage in stages):
        return None
    return stages


def _handler(arguments: dict) -> ToolResult:
    # Per the tool's own contract: check restart before command.
    if arguments.get("restart"):
        return ToolResult(ok=True, data="bash session reset (stateless handler — nothing to restart yet)")

    command = arguments.get("command", "")
    if not command.strip():
        return ToolResult(ok=False, error_code="empty_command")

    if any(op in command for op in DISALLOWED_OPERATORS):
        return ToolResult(ok=False, error_code="shell_operator_rejected")

    try:
        argv = shlex.split(command)
    except ValueError as exc:  # unbalanced quotes, e.g.
        return ToolResult(ok=False, error_code=f"parse_error: {exc}")

    stages = _split_pipeline(argv)
    if stages is None:
        return ToolResult(ok=False, error_code="empty_pipeline_stage")
    if len(stages) > MAX_PIPELINE_STAGES:
        return ToolResult(ok=False, error_code="too_many_pipeline_stages")
    for stage in stages:
        if stage[0] not in ALLOWED_EXECUTABLES:
            return ToolResult(ok=False, error_code=f"executable_not_allowed: {stage[0]}")
        for arg in stage[1:]:
            # Every argument, not just path-looking ones: a flag or pattern
            # ("-la", "apple|banana") resolves harmlessly inside the
            # workspace, so there is no need to guess which args are paths.
            if resolve_within_workspace(WORKSPACE, arg) is None:
                return ToolResult(ok=False, error_code=f"argument_escapes_workspace: {arg}")

    procs: list[subprocess.Popen] = []
    try:
        upstream_stdout = None
        for stage in stages:
            proc = subprocess.Popen(
                stage,
                shell=False,  # argv form, not a shell string — no operator injection
                cwd=WORKSPACE,
                stdin=upstream_stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if upstream_stdout is not None:
                upstream_stdout.close()  # our end; the child now owns the read side
            upstream_stdout = proc.stdout
            procs.append(proc)

        stdout, stderr = procs[-1].communicate(timeout=10)
        for upstream in procs[:-1]:
            upstream.wait(timeout=10)
    except subprocess.TimeoutExpired:
        for proc in procs:
            proc.kill()
        return ToolResult(ok=False, error_code="timeout")

    returncode = procs[-1].returncode
    output = (stdout or "") + (stderr or "")  # tool contract: combined stdout+stderr
    if returncode != 0:
        return ToolResult(ok=False, data=output, error_code=f"exit_{returncode}")
    return ToolResult(ok=True, data=output)


bash = Tool(
    name="bash",
    handler=_handler,
    anthropic_type="bash_20250124",
    side_effect=False,  # true today only because the allowlist is read-only
)
