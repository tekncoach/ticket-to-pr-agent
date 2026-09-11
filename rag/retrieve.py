# Verbatim starter skeleton from Day 4 (a10x.dev/sprint?track=build#day-4),
# copied as-is. Not wired to anything yet — see docs/ and the Day 4 corpus
# proposal for the design decisions to apply on top of this before it's
# real.

# rag/retrieve.py
def search_kb(query: str, k: int = 6, filters: dict | None = None) -> list[dict]:
    """Return [{id, text, score, source, title, citation}]"""
    ...

# System prompt fragment
GROUNDING = """
You answer ONLY from tool results. For each factual claim, cite [source#chunk_id].
If retrieval scores are low or sources conflict, respond with:
INSUFFICIENT_CONTEXT: <what is missing>
Never invent ticket IDs, policies, or URLs.
"""
