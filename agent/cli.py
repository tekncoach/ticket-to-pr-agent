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
# The fast path, kept alongside agent/service.py (the HTTP path) — both
# build their AgentRuntime from agent/factory.py so they can't drift apart.
from __future__ import annotations

import sys

from agent.factory import build_runtime


def main() -> None:
    if len(sys.argv) < 2:
        print('usage: python -m agent.cli "<message>"', file=sys.stderr)
        raise SystemExit(1)

    user_msg = sys.argv[1]
    result = build_runtime().run(user_msg)
    print(result)


# The "only run this when executed directly" guard — Python has no
# equivalent convention baked into the language the way Ruby scripts
# just run top to bottom; `python -m agent.cli` sets __name__ to
# "__main__" only for the module actually invoked, so importing this
# file from elsewhere (a test, for instance) never triggers main().
if __name__ == "__main__":
    main()
