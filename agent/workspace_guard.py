# agent/workspace_guard.py
#
# Shared path-confinement check for every tool that takes a filesystem
# path from untrusted model output. Extracted from tools/edit_file.py
# (where it already existed, tested, as _resolve_safe_path) so tools/bash.py
# can use the exact same logic on its own arguments instead of a second,
# slightly different implementation that could drift out of sync with it.
from __future__ import annotations

from pathlib import Path


def resolve_within_workspace(workspace: Path, raw_path: str) -> Path | None:
    """Resolve raw_path against workspace; None if it escapes.

    pathlib's own `/` operator discards the left side entirely when the
    right side is absolute (`Path("/workspace") / "/etc/passwd" ==
    Path("/etc/passwd")`), so an absolute-path argument is caught by the
    same relative_to() check below without special-casing it — verified,
    not assumed, in evals/test_bash_tool.py and evals/test_edit_file_tool.py.
    Also catches ".." traversal past the root and a symlink resolving
    outside it.
    """
    root = workspace.resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
