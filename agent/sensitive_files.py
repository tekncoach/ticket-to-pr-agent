# agent/sensitive_files.py
#
# Which file names are off limits, and how a tool asks.
#
# One definition, used by the shell and by the editor, so the two cannot disagree
# about what a credential file is. They disagreed before: the editor refused two
# names configured for the reference target and the shell refused none.
#
# Names only. This is not a scan for secrets inside files that are allowed, and a
# secret committed into source code, or into a file's history, is not covered. The
# customer-facing risk memo says so.
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from agent.config import SENSITIVE_FILE_PATTERNS

# Read by everyone and holding no secret. Exempting them keeps the guard one
# people leave on.
TEMPLATE_SUFFIXES = ("example", "sample", "template", "dist", "tpl")


def sensitive_pattern(name: str) -> str | None:
    """The pattern this base name matches, or None."""
    lowered = name.lower()
    if lowered.startswith(".env.") and lowered.rsplit(".", 1)[-1] in TEMPLATE_SUFFIXES:
        return None
    return next((p for p in SENSITIVE_FILE_PATTERNS if fnmatchcase(lowered, p)), None)


def sensitive_arg(workspace: Path, arg: str, git: bool = False) -> str | None:
    """The pattern an argument to a shell command refers to, or None.

    An argument counts only if it names a file that is actually there, so a search
    pattern that happens to look like a credential name ("config.key") is left
    alone: refusing it would break an ordinary grep and protect nothing. Git is the
    exception. `git show HEAD:.env` and `git log -- .env` read a file out of
    history that need not exist on disk, so for git the name is enough, and the
    part after a colon is read as a path.
    """
    if not arg or arg.startswith("-"):
        return None
    candidates = [arg]
    if ":" in arg:
        candidates.append(arg.rsplit(":", 1)[-1])
    for candidate in candidates:
        name = candidate.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        pattern = sensitive_pattern(name)
        if pattern is None:
            continue
        if git or (workspace / candidate).resolve().exists():
            return pattern
    return None


def grep_exclusions() -> list[str]:
    """`--exclude` flags that keep a recursive grep out of credential files.

    The shell cannot refuse `grep -r KEY .` by looking at its arguments, because
    the file it would read is never named. Adding the exclusions to the command
    means the walk skips them, and the search still covers everything else.
    """
    return [f"--exclude={pattern}" for pattern in SENSITIVE_FILE_PATTERNS]


def is_recursive_grep(args: list[str]) -> bool:
    for arg in args:
        if arg in ("--recursive", "--dereference-recursive"):
            return True
        if arg.startswith("-") and not arg.startswith("--") and any(c in arg[1:] for c in "rR"):
            return True
    return False
