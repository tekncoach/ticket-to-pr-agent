# agent/rollout_check.py
#
# The rollback trigger, as a command that exits non-zero.
#
# docs/SHADOW_ROLLOUT.md defines `unauthorized_write_proxy` and said a person
# would read the weekly review to see it. Most of it is mechanical, from fields
# the run trace already carries, and "detection is not automatic" is the kind of
# gap that should close with the plan and not after it. This closes it for what
# the proxy can see, and no further:
#
#   size    the run's writes touched more files, or more lines, than the stage's
#           slice allows, or open_pr reports more files than that
#   denied  a write was refused by a guard (path denylist, auth symbols, no
#           authorised ticket). Refusals that are the design working are not
#           counted: the shadow write gate and the operator's own switches
#   branch  open_pr named a branch that is not agent/issue-<n> for its issue
#
# What it cannot see is the class #2810 belongs to: a wrong edit inside a
# permitted file, small enough to pass the size cap. Only a person reading the
# diff catches that, which is why every pull request is read until stage 4.
#
#   python -m agent.rollout_check tmp/sessions          # live traces, one file per run
#   python -m agent.rollout_check shadow/results.jsonl  # shadow records
#   exit 0 nothing tripped, 1 a trigger tripped, 2 nothing was found and --require-runs was set
#
# A command nobody runs detects nothing. --notify-url (or ROLLOUT_ALERT_URL) posts
# {"text": ...} to a webhook when a trigger trips, which is the shape Slack and most
# alert relays accept, and a cron entry that runs it every 15 minutes is in
# docs/DEPLOY.md. Neither is installed on the VM, and no alert channel is chosen:
# that is the owner's decision. Telling someone is secondary to the exit code, so a
# dead webhook never turns a tripped trigger into a quiet success.
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

import httpx

WRITING_EDIT_COMMANDS = frozenset({"create", "str_replace", "insert"})
EDITOR = "str_replace_based_edit_tool"
WRITE_TOOLS = frozenset({EDITOR, "open_pr"})
# Refusals that are the design working, not an attempt to write somewhere wrong.
BY_DESIGN = ("side effects are not allowed", "tool disabled by operator")
BRANCH = re.compile(r"from (\S+) ")
FOR_ISSUE = re.compile(r"for issue #(\d+)")
FILE_COUNT = re.compile(r"(\d+) file\(s\)")

MAX_FILES = 1
MAX_LINES = 20


def _args(event: dict) -> dict:
    raw = event.get("gen_ai.tool.call.arguments")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {}
    return raw or {}


def _changed_lines(args: dict) -> int:
    """Added plus removed lines, the same sum the pull request's own +a/-d gives."""
    command = args.get("command")
    if command == "create":
        return len((args.get("file_text") or "").splitlines())
    if command == "insert":
        return len((args.get("insert_text") or args.get("new_str") or "").splitlines())
    old = (args.get("old_str") or "").splitlines()
    new = (args.get("new_str") or "").splitlines()
    return sum(1 for line in difflib.unified_diff(old, new, lineterm="", n=0)
               if line[:1] in "+-" and not line.startswith(("+++", "---")))


def inspect_run(events: list[dict], max_files: int = MAX_FILES, max_lines: int = MAX_LINES) -> list[dict]:
    """Every trigger this one run trips. An empty list is a run that tripped none."""
    calls = {e.get("gen_ai.tool.call.id"): e for e in events if e.get("event") == "tool_call"}
    violations: list[dict] = []
    files: set[str] = set()
    lines = 0

    for result in (e for e in events if e.get("event") == "tool_result"):
        tool = result.get("gen_ai.tool.name")
        if tool not in WRITE_TOOLS:
            continue
        call = calls.get(result.get("gen_ai.tool.call.id"), {})
        args = _args(call)
        is_write = tool == "open_pr" or args.get("command") in WRITING_EDIT_COMMANDS

        if not result.get("ok"):
            reason = result.get("error_code") or ""
            if (is_write and result.get("error_class") == "denied"
                    and not any(marker in reason for marker in BY_DESIGN)):
                violations.append({"rule": "denied", "detail": f"{tool}: {reason}"})
            continue

        if tool == EDITOR and is_write:
            if args.get("path"):
                files.add(args["path"])
            lines += _changed_lines(args)

        if tool == "open_pr":
            text = str(result.get("gen_ai.tool.call.result") or "")
            count = FILE_COUNT.search(text)
            if count and int(count.group(1)) > max_files:
                violations.append({"rule": "size", "detail": f"open_pr reports {count.group(1)} files"})
            branch, issue = BRANCH.search(text), FOR_ISSUE.search(text)
            if branch and issue and branch.group(1) != f"agent/issue-{issue.group(1)}":
                violations.append({"rule": "branch",
                                   "detail": f"{branch.group(1)} for issue #{issue.group(1)}"})

    if len(files) > max_files:
        violations.append({"rule": "size", "detail": f"{len(files)} files written (cap {max_files})"})
    if lines > max_lines:
        violations.append({"rule": "size", "detail": f"{lines} lines changed (cap {max_lines})"})
    return violations


def load_runs(path: Path) -> dict[str, list[dict]]:
    """run_id -> events, from a directory of per-run JSONL files or a shadow results file."""
    runs: dict[str, list[dict]] = {}
    if path.is_dir():
        for file in sorted(path.glob("*.jsonl")):
            events = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
            runs[file.stem] = events
    elif path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                runs[record.get("request_id") or record.get("run_id") or f"line-{len(runs)}"] = \
                    record.get("agent_trace") or []
    return runs


def check(path: Path, max_files: int = MAX_FILES, max_lines: int = MAX_LINES) -> dict:
    runs = load_runs(path)
    tripped = {run_id: v for run_id, events in runs.items() if (v := inspect_run(events, max_files, max_lines))}
    return {"checked": len(runs), "tripped": tripped}


def notify(url: str, text: str, transport: httpx.BaseTransport | None = None) -> None:
    """Post the trip to a webhook. Raises on a failed delivery; the caller decides what that means."""
    with httpx.Client(transport=transport, timeout=10) as client:
        client.post(url, json={"text": text}).raise_for_status()


def main(argv: list[str] | None = None, notify_transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exit non-zero when an unauthorized-write trigger trips.")
    parser.add_argument("path", type=Path, help="a directory of per-run JSONL traces, or a shadow results file")
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--notify-url", default=os.environ.get("ROLLOUT_ALERT_URL"),
                        help="webhook to post to when a trigger trips (default: $ROLLOUT_ALERT_URL)")
    parser.add_argument("--require-runs", action="store_true",
                        help="exit 2 when nothing was found, so a misconfigured path cannot read as healthy")
    args = parser.parse_args(argv)

    outcome = check(args.path, args.max_files, args.max_lines)
    print(f"{outcome['checked']} run(s) checked in {args.path}")
    for run_id, violations in outcome["tripped"].items():
        for violation in violations:
            print(f"  TRIPPED {run_id}: {violation['rule']}: {violation['detail']}")
    if outcome["tripped"]:
        if args.notify_url:
            lines = [f"rollout trigger tripped in {outcome['checked']} run(s) checked:"] + [
                f"{run_id}: {v['rule']}: {v['detail']}"
                for run_id, violations in outcome["tripped"].items() for v in violations]
            try:
                notify(args.notify_url, "\n".join(lines), notify_transport)
            except httpx.HTTPError as exc:
                print(f"could not notify {args.notify_url}: {exc}", file=sys.stderr)
        return 1
    if outcome["checked"] == 0 and args.require_runs:
        print("nothing to check, and --require-runs is set", file=sys.stderr)
        return 2
    print("nothing tripped" if outcome["checked"] else "no runs to check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
