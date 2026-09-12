# agent/mcp_server.py
#
# Exposes fetch_ticket as an MCP tool. Nothing to do with AgentRuntime: an
# MCP server executes the tool directly when a client calls it — it never
# calls a model itself. The model, if any, lives on the MCP client side
# (Claude Desktop, another agent, ...); we just answer "here's the ticket."
#
# Streamable HTTP, not stdio: we want the "stateless request/response
# core" of the current (2026-07-28) spec, which stdio has
# no equivalent concept for (no auth, no request/response framing over a
# transport — it's just a subprocess pipe). stateless_http=True is passed
# explicitly: the SDK's default (False) still layers an optional session
# concept (resumability, idle timeout) on top of the wire protocol, which
# is the older, session-based model the spec deprecated.
#
# Real OAuth (auth=AuthSettings(...), token_verifier=...) is a named,
# deferred fork here, not built: this server is a local POC demo, not a
# service exposed on the public internet — the same call this project's
# SPEC.md already makes for other pieces (name the fork, build it when the
# trigger to revisit actually arrives).
#
# Run it:   uv run python -m agent.mcp_server
# Listens:  http://127.0.0.1:8765/mcp
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from tools.fetch_ticket import fetch_ticket as _fetch_ticket

mcp = MCPServer("ticket-to-pr-agent")


@mcp.tool(name="fetch_ticket", description=_fetch_ticket.description)
def fetch_ticket_tool(issue_id: int) -> dict:
    """Fetch a GitHub Issue's title and body from the configured target repo."""
    result = _fetch_ticket.handler({"issue_id": issue_id})
    if not result.ok:
        raise ValueError(result.error_code)
    return result.data


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True)
