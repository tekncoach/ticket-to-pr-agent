# tools/search_kb.py
#
# Wraps rag.retrieve.search_kb as a Tool, with the same Tool/ToolResult
# contract every other tool here uses (rag/query.py is the human-facing
# equivalent). Citation and refusal are enforced by the GROUNDING rule in
# agent/factory.py's SYSTEM_PROMPT, not by this tool.
from __future__ import annotations

from agent.runtime import Tool, ToolResult
from rag.embeddings import EmbeddingServiceError
from rag.retrieve import search_kb as _search_kb

# "acl" is deliberately absent. It used to be here, so the model — or
# untrusted text it reasons over, like a ticket body — could pass
# filters={"acl": "internal"} and _build_filters() would honor it: privilege
# escalation with no server-side override. Which ACL bucket gets searched is
# a caller-identity decision, enforced in code, not a schema convention a
# hostile prompt could exploit. "collection" staying settable is deliberate:
# it's a corpus-organization label, identical for every caller, and every
# collection today is acl="public" — narrowing to one grants no new access.
_ALLOWED_FILTER_KEYS = ("source", "title", "section", "collection")

# Single service account today — no per-user identity to vary this by.
# Hardcoded until the per-user rights design in docs/research/mcp-server.md
# exists; same trigger to revisit as named there.
DEFAULT_ACL = "public"


def _handler(arguments: dict) -> ToolResult:
    query = arguments.get("query")
    if not query:
        return ToolResult(ok=False, error_code="missing_query")

    filters = dict(arguments.get("filters") or {})
    filters.pop("acl", None)  # defense in depth: never trust a caller-supplied value, even if the schema is ever loosened
    filters["acl"] = DEFAULT_ACL

    try:
        results = _search_kb(
            query,
            k=arguments.get("k", 6),
            filters=filters,
        )
    except ValueError as exc:
        # _build_filters' guard against an unknown filter key: a
        # schema-shaped mistake deserves its own error_code, not the
        # generic handler_error the dispatch loop would otherwise produce.
        return ToolResult(ok=False, error_code=f"invalid_filters: {exc}")
    except EmbeddingServiceError as exc:
        # embed() already retried with backoff before raising — a timeout
        # or 5xx shouldn't surface as an opaque handler_error.
        return ToolResult(ok=False, error_code=f"embedding_service_unavailable: {exc}")

    # "source" is the corpus's real absolute local path — fine for the
    # human-facing CLI, not for the agent: seen live handing Claude a target
    # it then tried to read outside the workspace entirely. citation + title
    # carry everything needed to ground an answer; source never reaches it.
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
