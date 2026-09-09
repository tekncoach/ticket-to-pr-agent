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
from tools.bash import bash
from tools.edit_file import edit_file
from tools.fetch_ticket import fetch_ticket
from tools.get_time import get_time

LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "1024"))
MAX_TURNS = int(os.environ.get("MAX_TURNS", "8"))
# The write gate: edit_file is side_effect=True, so it's rejected unless
# allow_side_effects is True. SHADOW_MODE=true (the safe default) means
# writes stay off; set SHADOW_MODE=false to actually let the agent edit.
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

SYSTEM_PROMPT = (
    "You are a coding agent that will grow into a ticket->PR agent. You can "
    "tell the time with get_time, inspect the checked-out repo with bash "
    "(read-only commands only: grep, cat, find, ls, head, tail, wc, pwd), "
    "read a GitHub Issue with fetch_ticket, and edit files with "
    "str_replace_based_edit_tool (view/create/str_replace/insert). Be concise."
)

# hello_agent.py kept two parallel structures in sync by hand: a TOOLS list
# of schemas and a separate TOOL_HANDLERS dict of callables. Our Tool
# dataclass bundles both into one object, so there's only one place to
# register a tool instead of two that can drift apart.
TOOLS: dict[str, Tool] = {
    "get_time": get_time,
    "bash": bash,
    "fetch_ticket": fetch_ticket,
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
