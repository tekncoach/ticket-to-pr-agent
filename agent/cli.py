# agent/cli.py
#
# Minimal entrypoint: build an AgentRuntime with one tool and run it.
#
#   uv run --env-file .env python -m agent.cli "what time is it in Paris?"
#
# --env-file is not optional: uv does NOT auto-load .env (that was a wrong
# assumption, corrected after testing) — without the flag, __post_init__
# raises "LLM_API_KEY is not set" before anything runs.
#
# No FastAPI, no uvicorn, no curl. This exists purely to exercise
# AgentRuntime.run() while we build out the loop body — the fast path,
# not the deployment path (that's FastAPI's job later, Day 6).
from __future__ import annotations

import os
import sys

from agent.runtime import AgentRuntime, Tool
from tools.bash import bash
from tools.edit_file import edit_file
from tools.fetch_ticket import fetch_ticket
from tools.get_time import get_time

# Same env-var names and defaults as hello_agent.py, so the two entrypoints
# stay configured the same way.
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

SYSTEM_PROMPT = (
    "You are a coding agent that will grow into a ticket->PR agent. You can "
    "tell the time with get_time, inspect the checked-out repo with bash "
    "(read-only commands only: grep, cat, find, ls, head, tail, wc, pwd), "
    "read a GitHub Issue with fetch_ticket, and edit files with "
    "str_replace_based_edit_tool (view/create/str_replace/insert). Be concise."
)

# hello_agent.py keeps two parallel structures in sync by hand: a TOOLS list
# of schemas and a separate TOOL_HANDLERS dict of callables. Our Tool
# dataclass bundles both into one object, so there's only one place to
# register a tool instead of two that can drift apart.
TOOLS: dict[str, Tool] = {
    "get_time": get_time,
    "bash": bash,
    "fetch_ticket": fetch_ticket,
    "str_replace_based_edit_tool": edit_file,
}


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m agent.cli "<message>"', file=sys.stderr)
        raise SystemExit(1)

    user_msg = sys.argv[1]
    runtime = AgentRuntime(
        model=LLM_MODEL, tools=TOOLS, system=SYSTEM_PROMPT,
        max_tokens=MAX_TOKENS, max_turns=MAX_TURNS,
        allow_side_effects=not SHADOW_MODE,
        thinking_enabled=THINKING_ENABLED, thinking_budget_tokens=THINKING_BUDGET_TOKENS,
    )
    result = runtime.run(user_msg)
    print(result)


# The "only run this when executed directly" guard — Python has no
# equivalent convention baked into the language the way Ruby scripts
# just run top to bottom; `python -m agent.cli` sets __name__ to
# "__main__" only for the module actually invoked, so importing this
# file from elsewhere (a test, for instance) never triggers main().
if __name__ == "__main__":
    main()
