# agent/cli.py
#
# Minimal entrypoint: build an AgentRuntime with one tool and run it.
#
#   uv run python -m agent.cli "what time is it in Paris?"
#
# No FastAPI, no uvicorn, no curl. This exists purely to exercise
# AgentRuntime.run() while we build out the loop body — the fast path,
# not the deployment path (that's FastAPI's job later, Day 6).
from __future__ import annotations

import os
import sys

from agent.runtime import AgentRuntime, Tool
from tools.get_time import get_time

# Same env-var name and default as hello_agent.py's LLM_MODEL, so the two
# entrypoints stay configured the same way.
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-haiku-4-5")

SYSTEM_PROMPT = (
    "You are a coding agent that will grow into a ticket->PR agent. For now the "
    "only thing you can do is tell the time: call the get_time tool when asked "
    "about the current time. Be concise."
)

# hello_agent.py keeps two parallel structures in sync by hand: a TOOLS list
# of schemas and a separate TOOL_HANDLERS dict of callables. Our Tool
# dataclass bundles both into one object, so there's only one place to
# register a tool instead of two that can drift apart.
TOOLS: dict[str, Tool] = {"get_time": get_time}


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m agent.cli "<message>"', file=sys.stderr)
        raise SystemExit(1)

    user_msg = sys.argv[1]
    runtime = AgentRuntime(model=LLM_MODEL, tools=TOOLS, system=SYSTEM_PROMPT)
    result = runtime.run(user_msg)
    print(result)


# The "only run this when executed directly" guard — Python has no
# equivalent convention baked into the language the way Ruby scripts
# just run top to bottom; `python -m agent.cli` sets __name__ to
# "__main__" only for the module actually invoked, so importing this
# file from elsewhere (a test, for instance) never triggers main().
if __name__ == "__main__":
    main()
