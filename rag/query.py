# rag/query.py
#
# A thin CLI over search_kb() for manually exploring what's in the index —
# raw retrieval results (score, citation, text), not a grounded LLM answer.
# Separate from wiring search_kb into AgentRuntime as a real tool (Day 4's
# remaining task) — that's for the agent; this is for a human to look.
from __future__ import annotations

import sys

from rag.retrieve import search_kb


def _print_results(results: list[dict]) -> None:
    if not results:
        print("(no results)")
        return
    for r in results:
        print(f"{r['score']:.4f}  {r['citation']}  ({r['source']})")
        print(f"  {r['text'][:220].replace(chr(10), ' ')}")
        print()


def main() -> None:
    # .strip() before the truthiness check: `make rag-query` with no Q=...
    # still passes one empty-string argv entry, not zero — argv length
    # alone can't tell "no query given" from "given an empty one".
    query = " ".join(sys.argv[1:]).strip()
    if query:
        _print_results(search_kb(query))
        return

    print("Type a question (empty line or Ctrl-D to quit).")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            break
        if not query:
            break
        _print_results(search_kb(query))


if __name__ == "__main__":
    main()
