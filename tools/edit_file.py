# tools/edit_file.py
#
# Anthropic-defined text_editor_20250728 client-side tool. Schema-less on
# the wire, same as bash — Claude already knows the input shape. This is
# the first write-classified tool: side_effect=True, so it's rejected
# unless AgentRuntime.allow_side_effects is True (agent/runtime.py's
# write gate, wired but dormant until this tool existed).
#
# Two independent safety layers, per Anthropic's own security note for
# this tool ("path is untrusted model output — confine every operation to
# a fixed project root"):
#   1. every path is resolved to its canonical form and checked against
#      WORKSPACE — rejects .., symlinks, absolute paths that escape it.
#   2. a denylist rejects specific paths even inside the workspace,
#      matching SPEC.md's Out of scope section.
#
# Known gap, named rather than hidden: the denylist works at the path
# level, so it fully covers crypto.py and migrations/ (whole files/dirs),
# but "no auth changes" cannot be — auth logic lives inside app.py,
# shared with plenty of non-auth code, and there is no dedicated auth
# file to deny. A path denylist cannot isolate a section within a file.
from __future__ import annotations

from pathlib import Path

from agent.config import WORKSPACE
from agent.runtime import Tool, ToolResult

DENYLIST = ("crypto.py", "migrations")


def _resolve_safe_path(raw_path: str) -> Path | None:
    root = WORKSPACE.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None  # escapes the workspace: .., a symlink, an absolute path elsewhere
    return candidate


def _is_denied(path: Path) -> bool:
    rel = path.relative_to(WORKSPACE.resolve())
    return any(part in DENYLIST for part in rel.parts) or rel.name in DENYLIST


def _handler(arguments: dict) -> ToolResult:
    command = arguments.get("command")
    raw_path = arguments.get("path")
    if not raw_path:
        return ToolResult(ok=False, error_code="missing_path")

    path = _resolve_safe_path(raw_path)
    if path is None:
        return ToolResult(ok=False, error_code="path_escapes_workspace")
    if _is_denied(path):
        return ToolResult(ok=False, error_code="path_denied")

    if command == "view":
        if not path.exists():
            return ToolResult(ok=False, error_code="not_found")
        if path.is_dir():
            return ToolResult(ok=True, data="\n".join(sorted(p.name for p in path.iterdir())))
        text = path.read_text()
        view_range = arguments.get("view_range")
        if view_range:
            start, end = view_range
            text = "\n".join(text.splitlines()[start - 1:end])
        return ToolResult(ok=True, data=text)

    if command == "create":
        if path.exists():
            path.with_suffix(path.suffix + ".bak").write_text(path.read_text())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments.get("file_text", ""))
        return ToolResult(ok=True, data=f"created {raw_path}")

    if command == "str_replace":
        if not path.exists():
            return ToolResult(ok=False, error_code="not_found")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")
        text = path.read_text()
        count = text.count(old_str)
        if count == 0:
            return ToolResult(ok=False, error_code="string_not_found")
        if count > 1:
            return ToolResult(ok=False, error_code="ambiguous_match")
        path.write_text(text.replace(old_str, new_str, 1))
        return ToolResult(ok=True, data=f"replaced 1 occurrence in {raw_path}")

    if command == "insert":
        if not path.exists():
            return ToolResult(ok=False, error_code="not_found")
        lines = path.read_text().splitlines()
        insert_line = arguments.get("insert_line")
        if insert_line is None or not (0 <= insert_line <= len(lines)):
            return ToolResult(ok=False, error_code="invalid_insert_line")
        lines.insert(insert_line, arguments.get("insert_text", ""))
        path.write_text("\n".join(lines) + "\n")
        return ToolResult(ok=True, data=f"inserted at line {insert_line} in {raw_path}")

    return ToolResult(ok=False, error_code=f"unknown_command: {command}")


edit_file = Tool(
    name="str_replace_based_edit_tool",  # Anthropic's fixed name for this tool type
    handler=_handler,
    anthropic_type="text_editor_20250728",
    side_effect=True,
)
