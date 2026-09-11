# tools/search_kb.py
#
# Wraps rag.retrieve.search_kb as a Tool the agent can actually call —
# rag/query.py already exposed it for a human; this is the same function
# for the agent, with the same Tool/ToolResult contract every other tool
# in this project uses.
#
# The GROUNDING citation/refusal rule (agent/factory.py's SYSTEM_PROMPT)
# is what turns raw search results into a trustworthy answer — this tool
# only returns them; it does not enforce citation or refusal itself.
from __future__ import annotations

from agent.runtime import Tool, ToolResult
from rag.retrieve import search_kb as _search_kb

_ALLOWED_FILTER_KEYS = ("source", "title", "section", "acl", "collection")


def _handler(arguments: dict) -> ToolResult:
    query = arguments.get("query")
    if not query:
        return ToolResult(ok=False, error_code="missing_query")

    try:
        results = _search_kb(
            query,
            k=arguments.get("k", 6),
            filters=arguments.get("filters"),
        )
    except ValueError as exc:
        # _build_filters' own guard against an unknown filter key — a
        # schema-shaped mistake worth its own error_code, not the
        # generic handler_error runtime.py's tool-dispatch loop would
        # otherwise produce for any other exception.
        return ToolResult(ok=False, error_code=f"invalid_filters: {exc}")

    # rag.retrieve.search_kb's "source" is the corpus's real, absolute
    # local filesystem path — fine for rag/query.py's human-facing CLI,
    # not for the agent: seen live giving Claude a target it then tried
    # to `bash find`/`view` outside the target repo's workspace entirely
    # (bash has no path confinement, only a read-only command allowlist —
    # see docs/SPEC.md). citation + title carry everything the agent
    # needs to ground and attribute an answer; source never reaches it.
    return ToolResult(ok=True, data=[
        {key: value for key, value in r.items() if key != "source"} for r in results
    ])


search_kb = Tool(
    name="search_kb",
    description=(
        "Search the engineering good-practices knowledge base (commit "
        "conventions, code-review checklists, testing guidance, agentic-SDLC "
        "prior art) for chunks relevant to a query. Returns "
        "[{id, text, score, title, citation}] - cite the citation "
        "field for every factual claim drawn from a result. If no result is "
        "relevant enough, say so with INSUFFICIENT_CONTEXT rather than "
        "answering from general knowledge."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question or topic to search the knowledge base for.",
            },
            "k": {
                "type": "integer",
                "description": "How many results to return. Defaults to 6.",
            },
            "filters": {
                "type": "object",
                "description": (
                    "Optional exact-match filters on chunk metadata. "
                    f"Allowed keys: {', '.join(_ALLOWED_FILTER_KEYS)}."
                ),
                "properties": {k: {"type": "string"} for k in _ALLOWED_FILTER_KEYS},
                "additionalProperties": False,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    handler=_handler,
    side_effect=False,
)
