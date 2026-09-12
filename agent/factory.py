# agent/factory.py
#
# Shared construction logic for every entrypoint (agent/cli.py, agent/service.py,
# and any future one). Reading env vars and building TOOLS/SYSTEM_PROMPT in two
# separate places would let the CLI and the service drift out of configuration
# sync — hello_agent.py never had this problem because it only had one
# entrypoint; we now have two, and this is the fix for that.
from __future__ import annotations

import os

from agent.event_sink import EventSink, JSONLFileSink, MultiSink, StdoutSink
from agent.runtime import AgentRuntime, Tool
from rag.retrieve import GROUNDING
from tools.bash import bash
from tools.comment_on_ticket import comment_on_ticket
from tools.edit_file import edit_file
from tools.fetch_ticket import fetch_ticket
from tools.search_kb import search_kb

LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1024"))
MAX_TURNS = int(os.environ.get("MAX_TURNS", "8"))
# The write gate: edit_file and comment_on_ticket are side_effect=True, so
# they're rejected unless allow_side_effects is True. SHADOW_MODE=true (the
# safe default) means writes stay off; set SHADOW_MODE=false to enable them.
# comment_on_ticket carries its own shadow check as well, so opening this
# gate is not on its own enough to start posting to a real repo.
SHADOW_MODE = os.environ.get("SHADOW_MODE", "true").lower() == "true"
# Prepared, off by default. If flipped on, raise MAX_TOKENS accordingly —
# the budget_tokens path (Haiku 4.5, our default) requires
# max_tokens > THINKING_BUDGET_TOKENS, checked in AgentRuntime.__post_init__.
THINKING_ENABLED = os.environ.get("THINKING_ENABLED", "false").lower() == "true"
THINKING_BUDGET_TOKENS = int(os.environ.get("THINKING_BUDGET_TOKENS", "2048"))
# Off by default: the JSONL file is always written (JSONLFileSink). Setting
# this also prints each event live to stdout as it happens — hello_agent.py's
# own "debug a loop you cannot see" technique.
LIVE_TRACE = os.environ.get("LIVE_TRACE", "false").lower() == "true"

# The runtime already turns a run it abandons into an actionable sentence
# (agent/runtime.py's stopped(), agent/errors.py's next_step()). This covers the
# other half: a tool that fails once while the run continues, where what the
# user ends up seeing is whatever the model decides to say about it. The failure
# is typed, so the model is told to read the type rather than guess from prose.
TOOL_FAILURES = (
    "Every tool failure comes back as '<class>: <detail>', where class is one "
    "of auth, denied, not_found, validation, rate_limit, unavailable, timeout, "
    "internal. Read the class, do not guess from the wording. auth and denied "
    "are final: stop, say plainly what is blocked and that a human has to "
    "unblock it, and do not try another tool to get around it. rate_limit, "
    "unavailable and timeout are transient and were already retried before you "
    "saw them: do not immediately repeat the same call. validation and "
    "not_found mean your arguments were wrong — fix them and try once more, "
    "then stop. Never invent a result a tool did not return, and never report "
    "success you did not observe. When you cannot finish, say what you were "
    "doing, what stopped you, and the one thing a person should do next — in a "
    "sentence they can act on, not an error code pasted back at them."
)

SYSTEM_PROMPT = (
    "You are a coding agent that will grow into a ticket->PR agent. bash "
    "(read-only: grep, cat, find, ls, head, tail, wc, pwd) and "
    "str_replace_based_edit_tool (view/create/str_replace/insert) only ever "
    "see the target repo's own checked-out code — never this project's "
    "engineering-practices knowledge base. fetch_ticket reads a GitHub "
    "Issue. search_kb is the ONLY way to consult the knowledge base "
    "(conventions, benchmarks, prior design reasoning) — for that kind of "
    "question, call search_kb directly; do not try to find the answer by "
    "exploring files with bash. Unless a question is obviously outside "
    "every tool's domain entirely (general knowledge with no plausible "
    "connection to engineering practice, this repo, or a ticket), call "
    "search_kb at least once before answering or refusing — a refusal "
    "must be grounded in what search_kb actually returned, not skipped "
    "on the assumption that nothing relevant exists. Be concise.\n"
    + TOOL_FAILURES + "\n"
    + GROUNDING
)

# hello_agent.py kept two parallel structures in sync by hand: a TOOLS list
# of schemas and a separate TOOL_HANDLERS dict of callables. Our Tool
# dataclass bundles both into one object, so there's only one place to
# register a tool instead of two that can drift apart.
TOOLS: dict[str, Tool] = {
    "bash": bash,
    "comment_on_ticket": comment_on_ticket,
    "fetch_ticket": fetch_ticket,
    "search_kb": search_kb,
    "str_replace_based_edit_tool": edit_file,
}


def llm_ready() -> bool:
    return bool(os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def build_logger() -> EventSink:
    return MultiSink(JSONLFileSink(), StdoutSink()) if LIVE_TRACE else JSONLFileSink()


def build_runtime() -> AgentRuntime:
    return AgentRuntime(
        model=LLM_MODEL, tools=TOOLS, system=SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS, max_turns=MAX_TURNS,
        allow_side_effects=not SHADOW_MODE,
        thinking_enabled=THINKING_ENABLED, thinking_budget_tokens=THINKING_BUDGET_TOKENS,
        logger=build_logger(),
    )
