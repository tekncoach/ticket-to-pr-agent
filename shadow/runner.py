# shadow/runner.py
#
# The shadow run: real input, live reads, every write a no-op that returns the
# payload it intended. One pairwise record per unit of traffic.
#
# Three things this file refuses to do, each because a drill names it:
#
#   It does not simulate reads. Only the consequence is removed, never the
#   evidence — a run against fixtures measures the fixtures.
#
#   It redacts at write time, not afterwards. Once a reporter's address is on
#   this disk it is on this disk, and every later step inherits that.
#
#   It does not treat its own SHADOW_MODE flag as proof that nothing was
#   written. shadow/audit.py asks the integration instead, because our flag and
#   our receipts are exactly what a bug in this file would have falsified.
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).parent
CLONES = HERE / "clones"
# Mirrors tools/edit_file.py: view changes nothing.
WRITING_EDIT_COMMANDS = frozenset({"create", "str_replace", "insert", "undo_edit"})
# A proposal needs room to be reached. The default eight turns died mid
# exploration on every unit, so the record carried a file list and no proposal
# — the one field the comparison is for.
MAX_TURNS = int(os.environ.get("SHADOW_MAX_TURNS", "30"))


def point_agent_at(repo: str, workspace: Path | None = None) -> Path:
    """Aim the agent at the repository this traffic came from.

    Must run BEFORE anything under agent/ is imported. agent/config.py reads
    TARGET_REPO and TARGET_WORKSPACE at import time and freezes them into
    module constants that tools/bash.py and tools/edit_file.py then hold, so
    setting the environment afterwards changes nothing and the run silently
    works against the wrong checkout — which is exactly what the first shadow
    batch did: sixty issues from one repository handed to an agent looking at
    another, refused every time for the obvious reason.
    """
    target = workspace or (CLONES / repo.replace("/", "-"))
    os.environ["TARGET_REPO"] = repo
    os.environ["TARGET_WORKSPACE"] = str(target)
    # run_tests needs the target's own interpreter, and a clone has no venv.
    # Pointed at ours so the tool fails with a clear import error rather than
    # a missing binary; shadow compares proposals, not green suites.
    os.environ.setdefault("TARGET_PYTHON", sys.executable)
    return target


def ensure_clone(repo: str, target: Path) -> bool:
    """A shallow checkout, so bash and the editor have something real to read."""
    if (target / ".git").exists():
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["git", "clone", "--depth", "50", f"https://github.com/{repo}.git", str(target)],
        capture_output=True, text=True, timeout=300)
    return done.returncode == 0


def _git(target: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(target), *args],
                          capture_output=True, text=True, timeout=timeout)


def checkout_base(target: Path, base_sha: str) -> str | None:
    """Put the tree where it was the moment before the fix landed.

    Without this the agent reads current main while working a ticket from
    2022, so it is asked for a change that is already there — and on #2715 it
    said exactly that, correctly, and the comparator scored it as half a hit
    because it had touched the right file. A baseline you cannot be at is not
    a baseline; this is the difference between replaying a ticket and quizzing
    the agent about a codebase that has already moved past it.

    Returns None on success, or why it could not, because a unit run against
    the wrong tree must be recorded as such rather than silently mixed in.
    """
    if not base_sha:
        return "no base_sha in the traffic record"
    # The clone is shallow, so an old commit is usually not there yet.
    if _git(target, "cat-file", "-e", f"{base_sha}^{{commit}}").returncode != 0:
        fetched = _git(target, "fetch", "--depth", "1", "origin", base_sha, timeout=300)
        if fetched.returncode != 0:
            return f"could not fetch {base_sha[:8]}: {fetched.stderr.strip()[:120]}"
    out = _git(target, "checkout", "--force", "--detach", base_sha)
    if out.returncode != 0:
        return f"could not check out {base_sha[:8]}: {out.stderr.strip()[:120]}"
    # The previous unit's shadow edits are no-ops, but a real clean keeps the
    # tree honest if that ever stops being true.
    _git(target, "clean", "-fd")
    return None

# Redaction beyond secrets: an issue body is written by a member of the public.
import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Greedy on the prefix: an earlier version matched from the third group on and
# left "+33 6 " sitting in the log, which is most of what identifies a number.
PHONE = re.compile(
    r"(?<![\w.])\+?\d[\d .()-]{7,17}\d(?![\w.])")
HANDLE = re.compile(r"(?<![\w/])@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")


def redact_deep(value):
    """Redact the strings inside a structure, never the structure itself.

    The first version redacted the serialised JSON, and the phone pattern ate
    the punctuation between fields — `"latency_ms": 1234.5, "x": 12` is a
    plausible phone number once the quotes stop mattering. It produced records
    that would not parse. Redaction belongs on values, where the shape is not
    part of what is being rewritten.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_deep(v) for v in value]
    return value


def redact(text: str) -> str:
    """Secrets, then the personal data a public issue carries.

    The project's own redactor first — it is what ships and what the eval
    suite checks — then the three patterns an issue tracker adds: addresses,
    phone numbers, and the handles that make a complaint attributable.
    """
    if not text:
        return text
    from agent.secrets_redaction import redact_secrets

    text = redact_secrets(text)
    text = EMAIL.sub("[EMAIL]", text)
    text = PHONE.sub("[PHONE]", text)
    return HANDLE.sub("[HANDLE]", text)


def shadowed_tools(tools: dict, intended: list[dict]) -> dict:
    """Every write tool replaced by a no-op that returns what it meant to do.

    side_effect stays True so the runtime's own accounting is unchanged, and
    the receipt carries the full arguments rather than a boolean — an answer
    quoting a file and a line needs something to be checked against, which is
    the same lesson the eval harness learned as F14.
    """
    from agent.runtime import Tool, ToolResult

    out = dict(tools)
    for name, tool in tools.items():
        if not tool.side_effect:
            continue

        def handler(arguments: dict, _name=name) -> ToolResult:
            # The editor is one tool with several commands and only some write.
            # Counting a `view` inflated writes_intended and put every file the
            # agent merely read into files_touched, which is the comparison's
            # own column. Same distinction tools/edit_file.py draws.
            if _name != "str_replace_based_edit_tool" or \
                    arguments.get("command") in WRITING_EDIT_COMMANDS:
                intended.append({"tool": _name, "arguments": arguments})
            return ToolResult(ok=True, data={
                "shadow": True,
                "tool": _name,
                "intended_args": arguments,
                "note": "recorded, not executed",
            })

        out[name] = Tool(name=name, handler=handler, description=tool.description,
                         input_schema=tool.input_schema, side_effect=True,
                         anthropic_type=tool.anthropic_type, repeatable=tool.repeatable)
    return out


@dataclass
class ShadowRecord:
    request_id: str
    input: str
    baseline: dict
    agent_proposal: dict
    agent_trace: list
    would_write: list
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    error: str | None = None
    # Which tree the agent actually read. None means the unit ran against the
    # base commit of its own pull request, which is the only tree where the
    # ticket is still open; a string says why it did not, and the comparator
    # refuses to score those.
    tree_error: str | None = None


def _proposal(outcome: dict, intended: list[dict]) -> dict:
    """What the agent would have done, in the terms the baseline is in.

    A proposal, not a result: the comparison is between two intentions, and
    calling ours a result would be the claim the day exists to avoid.
    """
    return {
        "answer": outcome.get("answer") or "",
        "writes_intended": len(intended),
        "files_touched": sorted({(w["arguments"] or {}).get("path")
                                 for w in intended
                                 if (w["arguments"] or {}).get("path")}),
        "tools_used": sorted({e["gen_ai.tool.name"] for e in outcome.get("trace", [])
                              if e.get("event") == "tool_call"}),
        "stopped_on": outcome.get("error"),
    }


def select_units(units: list[dict], earlier: list[dict], limit: int,
                 skip_done: bool) -> tuple[list[dict], list[dict]]:
    """Which units to run now, and which earlier records to keep.

    Growing a batch in slices, so each slice's cost is measured before the
    next is paid for. A record counts as done only if it ran on its own base
    commit — a wrong-tree record is exactly the one worth running again, and
    it is dropped rather than kept beside its replacement.
    """
    if not skip_done:
        return units[:limit], []
    kept = [r for r in earlier if not r.get("tree_error")]
    done = {r["request_id"] for r in kept}
    return [u for u in units if u["request_id"] not in done][:limit], kept


def shadow_prompt(unit: dict, workspace) -> str:
    """What the agent is told on a repository it has never seen.

    It names the workspace. The first version said only "you are inside a
    checkout", so the agent guessed /repo/... and was refused as escaping the
    workspace — in all three units of the first batch, before anything else
    went wrong. agent/tickets.py's own task_prompt has named it since day 4;
    this prompt was written separately and did not (F42).

    The other two paragraphs answer the other two stop reasons that batch
    produced: the agent improvised heredocs and `python -c` to write (F43),
    and tried pytest directly when run_tests failed on a clone with no
    virtualenv (F44). Naming a constraint is a mitigation, not a fix — both
    rows stay open.
    """
    return (f"Work issue #{unit['issue']} on {unit['repo']}.\n\n"
            f"{unit['title']}\n\n{unit['body']}\n\n"
            f"You are inside a checkout of that repository at {workspace}. "
            f"Every path is relative to its root: `ls`, `cat httpx/_client.py` "
            f"and `grep -rn x httpx/` work directly. Never write a path "
            f"starting /repo — it does not exist.\n"
            f"bash is read-only: grep, cat, find, ls, head, tail, wc, pwd, "
            f"sed, awk and git, reading only. No redirects, no heredocs, no "
            f"`python -c`, no `&&` — a single pipe is the one operator that "
            f"works, and the editor tool is how you change a file.\n"
            f"run_tests will not work here: this is a clone without its own "
            f"virtualenv, and a shadow run compares proposals rather than "
            f"green suites. Do not try to run pytest another way.\n"
            f"Make the change with the editor, then STOP and state in two or "
            f"three sentences which files you changed and why. Do not open a "
            f"pull request.")


def run_unit(unit: dict, model: str | None = None) -> ShadowRecord:
    # Imported here, after point_agent_at has run.
    from agent.factory import build_runtime

    intended: list[dict] = []
    runtime = build_runtime(model=model)
    # Reads stay live. Writes succeed and do nothing.
    #
    # The first version closed the runtime's write gate instead, and the gate
    # answers DENIED — so the agent tried to edit, was refused, tried again and
    # stopped on repeated_tool_failure without ever stating what it would have
    # changed. A refusal is not a shadow: the whole point is a real run that
    # produces a real proposal, with only the consequence removed. A gate says
    # no; shadow says done.
    runtime.allow_side_effects = lambda: True
    runtime.tools = shadowed_tools(runtime.tools, intended)
    runtime.max_turns = MAX_TURNS

    from agent.config import WORKSPACE

    prompt = shadow_prompt(unit, WORKSPACE)
    started = time.time()
    try:
        outcome = runtime.run(redact(prompt))
        error = outcome.get("error")
    except Exception as exc:  # noqa: BLE001 — one unit failing must not end a batch
        outcome, error = {"answer": "", "trace": []}, f"{type(exc).__name__}: {exc}"
    elapsed = (time.time() - started) * 1000

    usage = [e for e in outcome.get("trace", []) if e.get("event") == "llm_call"]
    trace = [e for e in outcome.get("trace", []) if e.get("event") != "message"]
    return ShadowRecord(
        request_id=unit["request_id"],
        input=redact(f"{unit['title']}\n\n{unit['body']}")[:4000],
        baseline=unit["baseline"],
        agent_proposal=redact_deep(_proposal(outcome, intended)),
        agent_trace=redact_deep(json.loads(json.dumps(trace, default=str))),
        would_write=intended,
        latency_ms=round(elapsed, 1),
        input_tokens=sum(e.get("gen_ai.usage.input_tokens") or 0 for e in usage),
        output_tokens=sum(e.get("gen_ai.usage.output_tokens") or 0 for e in usage),
        cached_tokens=sum(e.get("gen_ai.usage.cache_read.input_tokens") or 0 for e in usage),
        error=error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run traffic through the agent, writing nothing.")
    parser.add_argument("--traffic", type=Path, default=HERE / "traffic.jsonl")
    parser.add_argument("--limit", type=int, default=3,
                        help="units to run; the batch is deliberately small, see shadow/README.md")
    parser.add_argument("--model", default=None)
    parser.add_argument("--workspace", type=Path, default=None,
                        help="existing checkout to use instead of cloning")
    parser.add_argument("--out", type=Path, default=HERE / "results.jsonl")
    parser.add_argument("--skip-done", action="store_true",
                        help="run only units with no valid record yet, and add to --out "
                             "rather than replace it")
    args = parser.parse_args()

    units = [json.loads(l) for l in args.traffic.read_text(encoding="utf-8").splitlines() if l.strip()]

    # Growing a batch in slices, so each slice's cost is measured before the
    # next is paid for. A record counts as done only if it ran on its own base
    # commit — a wrong-tree record is exactly the one worth running again.
    earlier = []
    if args.skip_done and args.out.exists():
        earlier = [json.loads(l) for l in args.out.read_text(encoding="utf-8").splitlines()
                   if l.strip()]
    units, kept = select_units(units, earlier, args.limit, args.skip_done)
    if not units:
        print(f"no traffic in {args.traffic} — run `make shadow-harvest REPO=...`")
        return 1

    # One repository per batch: the agent's target is frozen at import, so a
    # mixed batch would run every unit against whichever repo came first.
    repos = {u["repo"] for u in units}
    if len(repos) > 1:
        print(f"this batch spans {sorted(repos)} — run one repository at a time")
        return 1

    repo = repos.pop()
    target = point_agent_at(repo, args.workspace)
    if not ensure_clone(repo, target):
        print(f"could not clone {repo} into {target}")
        return 1
    print(f"agent pointed at {repo} in {target}\n")

    records = []
    for i, unit in enumerate(units, 1):
        # Each unit at its own base commit: the tree as it was the moment
        # before the fix landed. Skipping this asks the agent for a change
        # that is already in the file it is reading.
        tree_error = checkout_base(target, unit.get("base_sha", ""))
        note = "" if not tree_error else f"   [{tree_error}]"
        print(f"  {i}/{len(units)}  {unit['request_id']}{note}", flush=True)
        record = run_unit(unit, args.model)
        record.tree_error = tree_error
        records.append(record)

    # Leave the clone somewhere sane rather than on the last unit's base.
    _git(target, "checkout", "--force", "-")

    # Redacted already, at build time. Written once, here — after the records
    # kept from earlier slices, so growing a batch never loses one.
    lines = [json.dumps(r, ensure_ascii=False) for r in kept]
    lines += [json.dumps(asdict(r), ensure_ascii=False) for r in records]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if kept:
        print(f"\n{len(kept)} earlier records kept, {len(records)} added")
    fresh = sum(r.input_tokens for r in records)
    cached = sum(r.cached_tokens for r in records)
    print(f"\n{len(records)} pairwise records -> {args.out}")
    print(f"input tokens: {fresh} fresh, {cached} from cache")
    print("zero writes is not proven here — run `make shadow-audit`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
