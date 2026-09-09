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
# through, and cwd is pinned to workspace/ so a command can't reach the
# rest of the machine.
#
# Read-only allowlist for now — real policy guards (write gating, arg
# validation, confirm=true) aren't built yet, so keeping every allowed
# executable read-only is the cheapest guard available before that exists.
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from agent.runtime import Tool, ToolResult

WORKSPACE = Path(__file__).resolve().parent.parent / "workspace" / "liberty-rider-myroadtrips"

ALLOWED_EXECUTABLES = {"grep", "cat", "find", "ls", "head", "tail", "wc", "pwd"}
SHELL_OPERATORS = ("&&", "||", "|", ";", "`", "$(", ">", "<", "\n")


def _handler(arguments: dict) -> ToolResult:
    # Per the tool's own contract: check restart before command.
    if arguments.get("restart"):
        return ToolResult(ok=True, data="bash session reset (stateless handler — nothing to restart yet)")

    command = arguments.get("command", "")
    if not command.strip():
        return ToolResult(ok=False, error_code="empty_command")

    if any(op in command for op in SHELL_OPERATORS):
        return ToolResult(ok=False, error_code="shell_operator_rejected")

    try:
        argv = shlex.split(command)
    except ValueError as exc:  # unbalanced quotes, e.g.
        return ToolResult(ok=False, error_code=f"parse_error: {exc}")

    if not argv or argv[0] not in ALLOWED_EXECUTABLES:
        return ToolResult(ok=False, error_code=f"executable_not_allowed: {argv[0] if argv else ''}")

    try:
        proc = subprocess.run(
            argv,
            shell=False,  # argv form, not a shell string — no operator injection
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error_code="timeout")

    output = proc.stdout + proc.stderr  # tool contract: return combined stdout+stderr
    if proc.returncode != 0:
        return ToolResult(ok=False, data=output, error_code=f"exit_{proc.returncode}")
    return ToolResult(ok=True, data=output)


bash = Tool(
    name="bash",
    handler=_handler,
    anthropic_type="bash_20250124",
    side_effect=False,  # true today only because the allowlist is read-only
)
