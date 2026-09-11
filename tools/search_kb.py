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

import httpx

from agent.runtime import Tool, ToolResult
from rag.retrieve import search_kb as _search_kb

# "acl" is deliberately NOT in this list. It used to be, alongside source/
# title/section/collection, which meant the model (or untrusted text it's
# reasoning over — a ticket body, a fetched issue) could call search_kb
# with filters={"acl": "internal"} and the equality filter in
# rag/retrieve.py's _build_filters() would honor it: a privilege-escalation
# path with no server-side override. Which ACL bucket gets searched is a
# caller-identity decision, not a search parameter the caller gets to
# choose — the same reasoning as bash's workspace confinement or
# edit_file's denylist, enforced in code, not left as a schema convention
# a model could ignore or a hostile prompt could exploit.
_ALLOWED_FILTER_KEYS = ("source", "title", "section", "collection")

# This project's auth model today is a single service account — no
# per-user identity to vary this by (see docs/research/mcp-server.md for
# the not-yet-built per-user rights design). Hardcoded until that exists;
# the trigger to revisit is the same one named there.
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
        # _build_filters' own guard against an unknown filter key — a
        # schema-shaped mistake worth its own error_code, not the
        # generic handler_error runtime.py's tool-dispatch loop would
        # otherwise produce for any other exception.
        return ToolResult(ok=False, error_code=f"invalid_filters: {exc}")
    except httpx.HTTPError as exc:
        # The embedding call (Hugging Face Inference Providers) is a
        # network call like any other tool's — a timeout or 5xx here
        # shouldn't surface as an opaque handler_error, same reasoning
        # as fetch_ticket's own httpx.RequestError handling.
        return ToolResult(ok=False, error_code=f"embedding_service_error: {exc}")

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
