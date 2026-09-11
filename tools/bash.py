# tools/bash.py
#
# Anthropic-defined bash_20250124 client-side tool. Schema-less on the wire
# (Claude already knows the input shape) — but Anthropic never executes it:
# this file is exactly the part that makes it actually run something.
#
# Per Anthropic's own security note for this tool: "apply an allowlist of
# permitted executables and reject shell operators (&&, |, ;, `, $()) — a
# blocklist is not sufficient." We also never use shell=True: argv form
# means shell metacharacters have no special meaning even if one slips
# through.
#
# cwd alone does NOT confine a command to the workspace — an argument can
# still be an absolute path or a `../` escape regardless of cwd, and this
# was live-verified to actually happen: given a path from outside the
# workspace (surfaced via search_kb's results, before that tool stopped
# exposing it), the agent ran `find /some/path/outside -name ...` and it
# succeeded. Every argument is now checked with the same
# agent.workspace_guard.resolve_within_workspace() tools/edit_file.py
# already used for its own path — one shared implementation, not two that
# could drift out of sync.
#
# One exception to "reject every operator": a plain pipe (`|`) between
# allowed, read-only executables (e.g. `find ... | wc -l`) isn't actually
# dangerous, so we build the pipeline ourselves with chained subprocess.Popen
# calls — never shell=True, so nothing else the model might slip in (&&, ;,
# backticks) gets shell interpretation either way.
#
# Read-only allowlist for now — real policy guards (write gating, arg
# validation, confirm=true) aren't built yet, so keeping every allowed
# executable read-only is the cheapest guard available before that exists.
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
            # Every argument, not just ones that "look like" a path — a
            # flag or a grep pattern resolves harmlessly inside the
            # workspace (e.g. "-la", "apple|banana"); only a genuine
            # escape (an absolute path, ".." past the root) ever fails
            # this check, so there is no need to first guess which
            # arguments are paths.
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
