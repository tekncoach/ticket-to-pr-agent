# rag/query.py
#
# A thin CLI over search_kb() for manually exploring what's in the index —
# raw retrieval results (score, citation, text), not a grounded LLM answer.
# Separate from search_kb as a registered AgentRuntime tool — that path is
# for the agent, this one is for a human to look.
from __future__ import annotations

import sys

from rag.retrieve import search_kb


def _print_results(results: list[dict], expand: bool) -> None:
    if not results:
        print("(no results)")
        return
    for r in results:
        print(f"{r['score']:.4f}  {r['citation']}  ({r['source']})")
        # Full chunk text, not a truncated preview — a chunk can be up to
        # max_chars (2200) and cutting it short (this used to stop at 220)
        # hides exactly the table/detail that makes a result useful,
        # making a genuinely good match look thin.
        text = r["section_text"] if expand and "section_text" in r else r["text"]
        for line in text.splitlines():
            print(f"  {line}")
        print()


def main() -> None:
    args = sys.argv[1:]
    expand = "--expand" in args
    if expand:
        args = [a for a in args if a != "--expand"]

    # .strip() before the truthiness check: `make rag-query` with no Q=...
    # still passes one empty-string argv entry, not zero — argv length
    # alone can't tell "no query given" from "given an empty one".
    query = " ".join(args).strip()
    if query:
        _print_results(search_kb(query, expand=expand), expand)
        return

    print("Type a question (empty line or Ctrl-D to quit).")
    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            break
        if not query:
            break
        _print_results(search_kb(query, expand=expand), expand)


if __name__ == "__main__":
    main()
