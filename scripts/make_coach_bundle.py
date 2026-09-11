#!/usr/bin/env python3
# scripts/make_coach_bundle.py
#
# Builds a coach-safe FILE BUNDLE from git-tracked files only, instead of
# relying on the coach's own GitHub tree/ URL auto-fetch — that path has a
# silent, opaque size/count cap that has already dropped exactly the
# files most relevant to a review without warning (see
# 1_projects/2026-09_A10x-14days-sprint/day 4/FEEDBACKS.md, response 1,
# and the coach-review-audit skill's checklist, section A). Building the
# bundle ourselves means we control exactly what's in it, nothing silently
# goes missing, and we can drop docs/ to save tokens on rounds where the
# code is what's under review, not the prose about it.
#
# Safe by construction, not by a denylist: only paths `git ls-files`
# returns are eligible. .env, .venv/, data/, tmp/, __pycache__ can never
# appear — they were never tracked in the first place, so there is
# nothing to accidentally forget to exclude.
#
# The "### <path>" section format and "FILE BUNDLE: N files" header match
# what the coach's own error messages describe when a submission arrives
# some other way (a bare blob/ or raw.githubusercontent.com link) — see
# the same FEEDBACKS.md responses 5-6.
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

# Adds no review value, burns tokens, or is binary/lockfile noise.
_SKIP_NAMES = {"uv.lock", "LICENSE"}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-docs", action="store_true",
                         help="Include docs/ (excluded by default to save tokens)")
    parser.add_argument("--only", nargs="*",
                         help="Only include paths starting with one of these prefixes, e.g. --only rag/ tools/search_kb.py")
    parser.add_argument("-o", "--output", default="/tmp/coach_bundle.txt")
    args = parser.parse_args()

    files = tracked_files()
    if not args.include_docs:
        files = [f for f in files if not f.startswith("docs/")]
    if args.only:
        files = [f for f in files if any(f.startswith(p) for p in args.only)]
    files = [f for f in files if Path(f).name not in _SKIP_NAMES]

    sections = []
    skipped_binary = []
    for f in files:
        try:
            text = Path(f).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            skipped_binary.append(f)
            continue
        sections.append(f"### {f}\n```\n{text}\n```")

    bundle = f"FILE BUNDLE: {len(sections)} files\n\n" + "\n\n".join(sections)
    Path(args.output).write_text(bundle)

    print(f"{len(sections)} files, {len(bundle):,} chars -> {args.output}")
    if skipped_binary:
        print(f"skipped (binary/unreadable): {', '.join(skipped_binary)}")


if __name__ == "__main__":
    main()
