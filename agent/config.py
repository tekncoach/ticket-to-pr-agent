# agent/config.py
#
# Single place naming the repo this agent operates on. Every tool imports
# REPO / WORKSPACE from here instead of hardcoding them — the seam a future
# multi-repo setup would plug into, without ripping up every tool that
# references the target repo. Not building multi-repo support itself yet:
# one repo, configurable, is what's needed today.
from __future__ import annotations

import os
from pathlib import Path

# "owner/repo" as GitHub's REST API identifies it.
REPO = os.environ.get("TARGET_REPO", "tekncoach/liberty-rider-myroadtrips")

# Local working copy that bash (and later edit_file / run_tests) operate on.
# Defaults to workspace/<repo-name>, derived from REPO so the two names
# can't silently drift apart; TARGET_WORKSPACE overrides the path directly
# if it ever needs to live somewhere else.
_default_workspace = Path(__file__).resolve().parent.parent / "workspace" / REPO.split("/")[-1]
WORKSPACE = Path(os.environ.get("TARGET_WORKSPACE", str(_default_workspace)))

# The target repo has its own pinned dependency set (its requirements-dev.txt),
# which is not ours — running its suite with our interpreter would test the
# wrong environment, or fail on imports we do not have. One venv inside the
# checkout, created at image build time, keeps the two apart.
TARGET_PYTHON = Path(os.environ.get("TARGET_PYTHON", str(WORKSPACE / ".venv" / "bin" / "python")))

def shadow_mode() -> bool:
    """Whether write tools are currently disabled. Read at CALL time.

    This is the kill switch, and reading it at import time would make it one
    that needs a restart to take effect — which is not a kill switch. Its whole
    value is that someone can stop writes during an incident in seconds,
    without a rebuild and without this laptop. One definition, used by the
    runtime's write gate, by /health, and by each write tool's own second
    check, so the three can never disagree about what is on.
    """
    # Writes are enabled by exactly one value, "false". Anything else, a typo
    # included, leaves the agent in shadow. This used to compare against "true",
    # so a malformed value turned writes ON: the switch an operator edits during
    # an incident failed open on the mistake most likely to be made then (F51).
    return os.environ.get("SHADOW_MODE", "true").strip().lower() != "false"


def writes_allowed() -> bool:
    return not shadow_mode()


def agent_enabled() -> bool:
    """Whether the agent may start a run at all. Read at CALL time.

    The bigger switch: SHADOW_MODE stops writes and keeps the agent observing,
    this one stops the agent, and the ticket goes back to whoever handled it
    before. It fails closed. Only an unset variable or the exact value "true"
    leaves the agent on; "false", "0", an empty string and a typo such as
    "flase" all turn it off, because the person flipping it during an incident
    is not the person who wrote it, and a switch that stays on after a
    misspelt value has not worked and has not said so.
    """
    return os.environ.get("AGENT_ENABLED", "true").strip().lower() == "true"


def disabled_tools() -> set[str]:
    """Tools the operator has turned off, by name. Read at CALL time.

    A comma-separated list, for the case where one tool is the problem and the
    rest of the agent is not: open_pr misbehaving should not cost the agent its
    ability to read a ticket. A name that matches no tool disables nothing, and
    /health lists those so a typo is visible rather than silent.
    """
    return {name.strip() for name in os.environ.get("DISABLED_TOOLS", "").split(",") if name.strip()}


# Per-run structured logs: one JSONL file per run_id, tmp/sessions/<run_id>.jsonl.
# One project (this repo) -> one directory is enough; no <project>/<session>
# nesting the way ~/.claude/projects/ needs, since that pattern exists to
# disambiguate between many projects sharing one global log root, a problem
# we don't have.
_default_sessions_dir = Path(__file__).resolve().parent.parent / "tmp" / "sessions"
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", str(_default_sessions_dir)))

# edit_file's path denylist can block a whole file
# (crypto.py) but can't isolate "no auth changes" when auth logic lives
# inside a shared file like app.py, alongside unrelated code — a path-level
# denylist has no concept of "this part of the file." These are the
# specific symbol names a diff touching them should be treated as an auth
# change even inside an otherwise-allowed file. Defaults match the
# reference target's (liberty-rider-myroadtrips) own auth code — that's
# real, not arbitrary, but also repo-specific: a different TARGET_REPO
# needs its own list, which is exactly why this is env-configurable rather
# than a constant inside tools/edit_file.py.
# get_session_user is deliberately NOT here, and the reason cost a run to
# learn: it is the dependency every protected endpoint declares
# (`user=Depends(get_session_user)`), so blocking any write that mentions it
# blocks writing a protected endpoint at all. The agent was asked to add one
# and was refused by our own guard.
#
# The distinction the list has to carry is define-or-alter versus call. These
# two are auth internals — nothing outside the auth code has a reason to name
# them, so a write that does is a write worth stopping. Naming the consumer
# facing dependency instead made the guard block correct work, which is how a
# guard gets switched off rather than fixed.
AUTH_SENSITIVE_SYMBOLS = tuple(
    s.strip() for s in os.environ.get(
        "AUTH_SENSITIVE_SYMBOLS", "_is_cross_site,SESSION_COOKIE",
    ).split(",") if s.strip()
)

# File names whose contents the agent must not read or write, whichever tool it
# reaches for. Found by testing: with a .env and a private key in the checkout,
# `cat .env`, `cat id_rsa`, `grep -r KEY .` and the editor's view all returned
# the secret, which would have gone to the model and into the run trace. The
# editor's own denylist is two names configured for the reference target
# (crypto.py, migrations) and the shell had none.
#
# Matched on the file's base name, case-insensitively, as glob patterns. Template
# names (.env.example and its kin) are exempt in agent/sensitive_files.py: a
# template holds no secret and everyone reads it. SENSITIVE_FILES_EXTRA adds
# names for a target and never replaces these, since a repository's secrets are
# not all called .env.
SENSITIVE_FILE_PATTERNS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".netrc", ".pgpass", ".git-credentials", "credentials.json",
    "secrets.json", "secrets.yml", "secrets.yaml",
) + tuple(
    s.strip().lower() for s in os.environ.get("SENSITIVE_FILES_EXTRA", "").split(",") if s.strip()
)
