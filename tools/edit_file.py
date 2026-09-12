# tools/edit_file.py
#
# Anthropic-defined text_editor_20250728 client-side tool, schema-less on
# the wire like bash. The only write-classified tool: side_effect=True, so
# it's rejected unless AgentRuntime.allow_side_effects is True.
#
# Three safety layers, the first two per Anthropic's security note ("path is
# untrusted model output — confine every operation to a fixed project root"):
#
# 1. Every path resolved to canonical form and checked against WORKSPACE —
#    rejects .., symlinks, absolute paths that escape it.
# 2. A denylist rejecting specific paths inside the workspace, matching
#    SPEC.md's Out of scope section.
# 3. _touches_auth_symbol() scans the text a write would add or remove for
#    an agent.config.AUTH_SENSITIVE_SYMBOLS name. A path denylist covers
#    whole files (crypto.py, migrations/) but cannot isolate a section
#    within one, and auth logic lives inside app.py among unrelated code —
#    so "no auth changes" needed a mechanism that ignores which file it's
#    in. Same "enforce in code, don't just describe the boundary" pattern
#    as bash's workspace confinement.
from __future__ import annotations

import re
from pathlib import Path

from agent.config import AUTH_SENSITIVE_SYMBOLS, WORKSPACE
from agent.errors import ErrorClass, ToolError
from agent.runtime import Tool, ToolResult
from agent.workspace_guard import resolve_within_workspace

DENYLIST = ("crypto.py", "migrations")


def _resolve_safe_path(raw_path: str) -> Path | None:
    return resolve_within_workspace(WORKSPACE, raw_path)


def _is_denied(path: Path) -> bool:
    rel = path.relative_to(WORKSPACE.resolve())
    return any(part in DENYLIST for part in rel.parts) or rel.name in DENYLIST


def _touches_auth_symbol(*texts: str) -> str | None:
    """None if none of AUTH_SENSITIVE_SYMBOLS appears as a whole word in any
    of texts, otherwise the first symbol found. Word-boundary matched so
    get_session_user doesn't also flag get_session_user_v2 or a comment that
    merely mentions the name. Checked against both the before and after text
    of a write: a diff that *removes* an auth check is exactly as much an
    auth change as one that adds a call to one."""
    for symbol in AUTH_SENSITIVE_SYMBOLS:
        pattern = rf"\b{re.escape(symbol)}\b"
        if any(re.search(pattern, text) for text in texts):
            return symbol
    return None


def _denied(detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.DENIED, detail)))


def _invalid(detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, detail)))


def _missing(detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.NOT_FOUND, detail)))


def _handler(arguments: dict) -> ToolResult:
    command = arguments.get("command")
    raw_path = arguments.get("path")
    if not raw_path:
        return _invalid("missing path")

    path = _resolve_safe_path(raw_path)
    if path is None:
        return _denied(f"path escapes workspace: {raw_path}")
    if _is_denied(path):
        return _denied(f"path is out of scope: {raw_path}")

    if command == "view":
        if not path.exists():
            return _missing(f"no such file: {raw_path}")
        if path.is_dir():
            return ToolResult(ok=True, data="\n".join(sorted(p.name for p in path.iterdir())))
        text = path.read_text()
        view_range = arguments.get("view_range")
        if view_range:
            start, end = view_range
            text = "\n".join(text.splitlines()[start - 1:end])
        return ToolResult(ok=True, data=text)

    if command == "create":
        file_text = arguments.get("file_text", "")
        old_text = path.read_text() if path.exists() else ""
        symbol = _touches_auth_symbol(old_text, file_text)
        if symbol:
            return _denied(f"auth symbol touched: {symbol}")
        if path.exists():
            path.with_suffix(path.suffix + ".bak").write_text(old_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_text)
        return ToolResult(ok=True, data=f"created {raw_path}")

    if command == "str_replace":
        if not path.exists():
            return _missing(f"no such file: {raw_path}")
        old_str = arguments.get("old_str", "")
        new_str = arguments.get("new_str", "")
        symbol = _touches_auth_symbol(old_str, new_str)
        if symbol:
            return _denied(f"auth symbol touched: {symbol}")
        text = path.read_text()
        count = text.count(old_str)
        if count == 0:
            return _missing(f"old_str not found in {raw_path}")
        if count > 1:
            return _invalid(f"old_str matches {count} times in {raw_path}; add surrounding context")
        path.write_text(text.replace(old_str, new_str, 1))
        return ToolResult(ok=True, data=f"replaced 1 occurrence in {raw_path}")

    if command == "insert":
        if not path.exists():
            return _missing(f"no such file: {raw_path}")
        insert_text = arguments.get("insert_text", "")
        symbol = _touches_auth_symbol(insert_text)
        if symbol:
            return _denied(f"auth symbol touched: {symbol}")
        lines = path.read_text().splitlines()
        insert_line = arguments.get("insert_line")
        if insert_line is None or not (0 <= insert_line <= len(lines)):
            return _invalid(f"insert_line must be between 0 and {len(lines)}")
        lines.insert(insert_line, insert_text)
        path.write_text("\n".join(lines) + "\n")
        return ToolResult(ok=True, data=f"inserted at line {insert_line} in {raw_path}")

    return _invalid(f"unknown command: {command}")


edit_file = Tool(
    name="str_replace_based_edit_tool",  # Anthropic's fixed name for this tool type
    handler=_handler,
    anthropic_type="text_editor_20250728",
    side_effect=True,
)
