# tools/bash.py
#
# Anthropic-defined bash_20250124 client-side tool: schema-less on the wire,
# but Anthropic never executes it — this file is what makes it run.
#
# Three guards, per Anthropic's security note ("an allowlist of permitted
# executables, reject shell operators; a blocklist is not sufficient"):
#
# 1. Allowlisted, read-only executables only. Read-only because real policy
#    guards (write gating, arg validation, confirm=true) don't exist yet.
# 2. Never shell=True. argv form means a metacharacter that slips through
#    has no special meaning anyway. A plain pipe between allowed executables
#    (`find ... | wc -l`) is the one operator permitted, built structurally
#    with chained Popen calls rather than handed to a shell.
# 3. Every argument resolved against the workspace. cwd alone confines
#    nothing — an absolute path or `../` escapes it regardless, live-verified:
#    the agent once ran `find /some/path/outside` successfully. Uses the same
#    agent.workspace_guard.resolve_within_workspace() as tools/edit_file.py,
#    one implementation so the two can't drift.
from __future__ import annotations

import re
import shlex
import subprocess
import time

from agent.config import WORKSPACE
from agent.errors import ErrorClass, ToolError
from agent.runtime import Tool, ToolResult
from agent.workspace_guard import resolve_within_workspace

ALLOWED_EXECUTABLES = {"grep", "cat", "find", "ls", "head", "tail", "wc", "pwd",
                       "sed", "awk", "git"}

# git reads the history the agent is about to add to — log, diff, show and
# blame answer "how does this codebase do things" better than any amount of
# grepping. Its writing half belongs to tools/open_pr.py, which owns the
# branch, the commit and the push, so bash gets the reading half only and the
# boundary is a subcommand allowlist rather than a blocklist of the dangerous
# ones: a subcommand nobody has vetted is refused by default.
_GIT_READ_SUBCOMMANDS = {"log", "diff", "show", "status", "blame", "ls-files",
                         "describe", "shortlog", "rev-parse", "grep",
                         # branch and tag LIST when given no name to create.
                         # `git branch -a` was refused in a real run for
                         # asking what branches exist, which is reading.
                         "branch", "tag", "remote", "config"}

# sed and awk are in the allowlist and are NOT read-only by nature: `sed -i`
# edits in place, and awk can redirect to a file from inside its own program
# text. They earn their place because reading a line range is what an agent
# asks for constantly, and refusing it sends the model hunting for another
# way rather than doing the work.
#
# So the boundary moves from "which executable" to "which invocation", and it
# is enforced here rather than hoped for: the in-place flags are rejected by
# name, and awk's program text is checked for the one thing that writes.
# Blocking the executable outright was the cheaper guard; this is the honest
# one, because the capability it withholds is exactly the dangerous half.
_WRITE_FLAGS = {"-i", "--in-place"}
_AWK_WRITE_RE = re.compile(r"(^|[^>])>[^>]|\bprintf?\s*>|\bsystem\s*\(")
# What remains genuinely dangerous, and why each one does. Command
# substitution runs an arbitrary program whose name never passes the
# allowlist, and file redirection writes — those are capabilities. The
# chaining operators are NOT: `a && b` runs two commands that each go through
# the same executable allowlist and the same per-argument confinement as a
# single one, so chaining adds sequencing, not reach. They were rejected
# because Anthropic's guidance says a blocklist is insufficient — but this is
# an allowlist, and the argument does not transfer.
DISALLOWED_OPERATORS = ("`", "$(", ">", "<", "\n")
CHAIN_OPERATORS = ("&&", "||", ";")

# Stderr redirections, stripped before the operator check rather than
# rejected. `2>/dev/null` and `2>&1` cannot write a file and cannot run
# anything — they only decide whether noise reaches stdout, and this handler
# already merges the two streams, so both are no-ops here. They were the
# single biggest cause of refusals across every real run: six of the nine
# rejected commands died on a suppression that changes nothing.
_STDERR_REDIRECTS = ("2>/dev/null", "2>&1", "2> /dev/null")

# `cd <somewhere> && <command>`. The prompt hands the agent the workspace's
# absolute path, so it reasonably uses it — and was then refused for the
# operator, which reads as the path being wrong when it was exactly right.
#
# Resolving the target answers the real question, with the guard that already
# exists: inside the workspace the cd is a NO-OP, because every command
# already runs with cwd=WORKSPACE, so it is stripped. Outside, it is an escape
# and gets the escape's own error rather than a misleading one about syntax.
_CD_PREFIX_RE = re.compile(r"""^\s*cd\s+(?P<path>"[^"]*"|'[^']*'|\S+)\s*(?:&&|;)\s*(?P<rest>.+)$""",
                           re.DOTALL)
MAX_PIPELINE_STAGES = 3
# Chained segments per call. A bound rather than a boundary: the guards that
# matter run on every segment regardless, this just keeps one call from
# becoming a script.
MAX_CHAIN_SEGMENTS = 6
_TIMEOUT_S = 10


def _split_chain(argv: list[str]) -> list[tuple[str, list[str]]] | None:
    """[(operator that PRECEDES this segment, its tokens)], "" for the first.

    None on an empty segment — a leading, trailing or doubled operator.
    """
    chain: list[tuple[str, list[str]]] = [("", [])]
    for tok in argv:
        if tok in CHAIN_OPERATORS:
            chain.append((tok, []))
        else:
            chain[-1][1].append(tok)
    return None if any(not tokens for _, tokens in chain) else chain


def _should_run(operator: str, previous_code: int | None) -> bool:
    """Shell semantics: && needs the previous to have succeeded, || needs it
    to have failed, ; runs regardless."""
    if previous_code is None or operator == ";":
        return True
    return previous_code == 0 if operator == "&&" else previous_code != 0


def _split_pipeline(argv: list[str]) -> list[list[str]] | None:
    """Split tokens on stand-alone "|" tokens into pipeline stages.

    shlex already resolved quoting before this runs, so a `|` that was
    inside quotes (e.g. grep -E "foo|bar") survived as part of one token,
    not as its own list element — only a bare, unquoted `|` reaches here as
    a stage boundary. Returns None on an empty stage (leading/trailing/
    doubled pipe, e.g. "grep foo |").
    """
    stages: list[list[str]] = [[]]
    for tok in argv:
        if tok == "|":
            stages.append([])
        else:
            stages[-1].append(tok)
    if any(not stage for stage in stages):
        return None
    return stages


def _expand_globs(args: list[str]) -> list[str]:
    expanded = []
    for arg in args:
        if arg.startswith("-") or not any(c in arg for c in "*?["):
            expanded.append(arg)
            continue
        matches = sorted(WORKSPACE.glob(arg))
        expanded.extend(str(m.relative_to(WORKSPACE)) for m in matches) if matches \
            else expanded.append(arg)
    return expanded


def _refuse_write_invocation(stage: list[str]) -> ToolResult | None:
    """None if this sed/awk call only reads, otherwise the refusal.

    Checked per argument rather than by scanning the whole command string: a
    filename containing "-i" is not an in-place flag, and a grep pattern
    containing ">" is not a redirect.
    """
    for arg in stage[1:]:
        if arg in _WRITE_FLAGS or (arg.startswith("-i") and stage[0] == "sed"):
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.DENIED, f"{stage[0]} may read, not write: {arg}")))
    if stage[0] == "awk" and any(_AWK_WRITE_RE.search(a) for a in stage[1:]):
        return ToolResult(ok=False, error_code=str(
            ToolError(ErrorClass.DENIED, "awk program writes or shells out")))
    if stage[0] == "git":
        # -C and -c take a VALUE, so the first non-dash argument after them is
        # that value, not the subcommand: `git -C . log` read as `git .`.
        # Same slip as open_pr's error message once made with `git -c`.
        rest, skip = [], False
        for arg in stage[1:]:
            if skip:
                skip = False
                continue
            if arg in ("-C", "-c"):
                skip = True
                continue
            rest.append(arg)
        subcommand = next((a for a in rest if not a.startswith("-")), "")
        stage_after_subcommand = rest[rest.index(subcommand) + 1:] if subcommand in rest else []
        # branch, tag and config read when listing and write when named: a
        # positional argument after them is the thing being created or set.
        # The subcommand allowlist says which verbs, this says which shape.
        if subcommand in ("branch", "tag", "config", "remote"):
            named = [a for a in stage_after_subcommand if not a.startswith("-")]
            if named:
                return ToolResult(ok=False, error_code=str(ToolError(
                    ErrorClass.DENIED,
                    f"git {subcommand} {named[0]} names something to change — "
                    f"bash reads, open_pr writes")))
        if subcommand not in _GIT_READ_SUBCOMMANDS:
            return ToolResult(ok=False, error_code=str(ToolError(
                ErrorClass.DENIED,
                f"git {subcommand or '(none)'} is not a read subcommand — "
                f"open_pr owns branching, committing and pushing")))
    return None


def _run_pipeline(stages: list[list[str]], timeout: float) -> tuple[str, int | None]:
    """(combined output, exit code). Exit code None means it timed out."""
    procs: list[subprocess.Popen] = []
    try:
        upstream_stdout = None
        for stage in stages:
            proc = subprocess.Popen(
                stage,
                shell=False,  # argv form, not a shell string — no operator injection
                cwd=WORKSPACE,
                stdin=upstream_stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if upstream_stdout is not None:
                upstream_stdout.close()  # our end; the child now owns the read side
            upstream_stdout = proc.stdout
            procs.append(proc)

        stdout, stderr = procs[-1].communicate(timeout=timeout)
        for upstream in procs[:-1]:
            upstream.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        for proc in procs:
            proc.kill()
        return "", None

    # tool contract: combined stdout+stderr
    return (stdout or "") + (stderr or ""), procs[-1].returncode


def _handler(arguments: dict) -> ToolResult:
    # Per the tool's own contract: check restart before command.
    if arguments.get("restart"):
        return ToolResult(ok=True, data="bash session reset (stateless handler — nothing to restart yet)")

    command = arguments.get("command", "")
    if not command.strip():
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, "empty command")))

    for redirect in _STDERR_REDIRECTS:
        command = command.replace(redirect, " ")

    cd = _CD_PREFIX_RE.match(command)
    if cd:
        target = cd.group("path").strip("\"'")
        if resolve_within_workspace(WORKSPACE, target) is None:
            return ToolResult(ok=False, error_code=str(ToolError(
                ErrorClass.DENIED, f"argument escapes workspace: {target}")))
        command = cd.group("rest")

    if any(op in command for op in DISALLOWED_OPERATORS):
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.DENIED, "shell operator rejected")))

    try:
        # punctuation_chars makes ";" its own token — plain shlex.split leaves
        # it stuck to the word beside it ("ls;" as an executable name) — while
        # anything quoted stays one token, so grep -E "x|y" keeps its pattern.
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        argv = list(lexer)
    except ValueError as exc:  # unbalanced quotes, e.g.
        return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.VALIDATION, str(exc))))

    chain = _split_chain(argv)
    if chain is None:
        return ToolResult(ok=False, error_code=str(
            ToolError(ErrorClass.VALIDATION, "empty command around a chaining operator")))
    if len(chain) > MAX_CHAIN_SEGMENTS:
        return ToolResult(ok=False, error_code=str(ToolError(
            ErrorClass.VALIDATION, f"more than {MAX_CHAIN_SEGMENTS} chained commands")))

    # Validate EVERY segment before running ANY of them. Checking as we go
    # would let `ls && rm -rf /` print a directory listing before refusing —
    # a refusal that arrives after the first half already ran is not a refusal.
    validated = []
    for _, segment in chain:
        stages = _split_pipeline(segment)
        if stages is None:
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.VALIDATION, "empty pipeline stage")))
        if len(stages) > MAX_PIPELINE_STAGES:
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.VALIDATION, f"more than {MAX_PIPELINE_STAGES} pipeline stages")))
        for stage in stages:
            if stage[0] in ("sed", "awk", "git"):
                refusal = _refuse_write_invocation(stage)
                if refusal:
                    return refusal
            if stage[0] not in ALLOWED_EXECUTABLES:
                return ToolResult(ok=False, error_code=str(
                    ToolError(ErrorClass.DENIED, f"executable not allowed: {stage[0]}")))
            # Globs, expanded here because there is no shell to do it. argv
            # goes straight to subprocess, so `tests/*.py` arrived as a literal
            # filename and grep exited 2 — a silent failure on an idiom every
            # agent reaches for. Expansion is ours, so every result still goes
            # through the same workspace check below; a pattern that matches
            # nothing is left as-is, which is what a shell with nullglob off does.
            stage[1:] = _expand_globs(stage[1:])

            for arg in stage[1:]:
                # Every argument, not just path-looking ones: a flag or pattern
                # ("-la", "apple|banana") resolves harmlessly inside the
                # workspace, so there is no need to guess which args are paths.
                if resolve_within_workspace(WORKSPACE, arg) is None:
                    return ToolResult(ok=False, error_code=str(
                        ToolError(ErrorClass.DENIED, f"argument escapes workspace: {arg}")))
        validated.append(stages)

    output, returncode = "", None
    deadline = time.monotonic() + _TIMEOUT_S
    for (operator, _), stages in zip(chain, validated):
        if not _should_run(operator, returncode):
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.TIMEOUT, f"command exceeded {_TIMEOUT_S}s")))
        segment_output, returncode = _run_pipeline(stages, remaining)
        if returncode is None:  # timed out
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.TIMEOUT, f"command exceeded {_TIMEOUT_S}s")))
        output += segment_output

    if returncode not in (0, None):
        # A non-zero exit from a read-only command is a RESULT, not a tool
        # failure — grep exiting 1 means "no match", which is an answer.
        # agent/runtime.py discards ToolResult.data when ok is False, so
        # reporting an empty grep as a failure throws away the very output
        # that says it was empty. ok=False stays for the tool itself failing:
        # a rejected operator, an escape, a timeout.
        return ToolResult(ok=True, data=output if output.strip()
                          else f"(exit {returncode}: no output)")
    return ToolResult(ok=True, data=output)


bash = Tool(
    name="bash",
    handler=_handler,
    anthropic_type="bash_20250124",
    side_effect=False,  # true today only because the allowlist is read-only
)
