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

# Per-run structured logs: one JSONL file per run_id, tmp/sessions/<run_id>.jsonl.
# One project (this repo) -> one directory is enough; no <project>/<session>
# nesting the way ~/.claude/projects/ needs, since that pattern exists to
# disambiguate between many projects sharing one global log root, a problem
# we don't have.
_default_sessions_dir = Path(__file__).resolve().parent.parent / "tmp" / "sessions"
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", str(_default_sessions_dir)))
