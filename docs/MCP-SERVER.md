# MCP server

`agent/mcp_server.py` exposes `fetch_ticket` as an MCP tool. It has no relationship to `agent/runtime.py` — an MCP server executes the tool directly when a client calls it, it never calls a model itself. The model, if any, lives on the MCP client side (Claude Desktop, another agent); the server just answers "here's the ticket."

## Why `fetch_ticket`, not `bash` or `edit_file`

`bash` and `edit_file` are Anthropic-defined client-side tool types (`bash_20250124`, `text_editor_20250728`) — schema-less, handled directly by the Messages API's own tool-use protocol, not something this project declares a schema for. `fetch_ticket` is the one tool this project owns a schema for end to end, making it the natural candidate to expose to a different protocol.

## Transport: Streamable HTTP, not stdio

stdio needs zero network exposure (the client launches the server as a subprocess and speaks over its stdin/stdout) but has no concept of request/response framing or auth — it's a private pipe. The current MCP spec's emphasis on a "stateless request/response core" and OAuth only makes sense over the network transport, so that's the one demonstrated here.

`mcp.run(transport="streamable-http", stateless_http=True, port=8765)` — `stateless_http=True` is passed explicitly: the SDK's default (`False`) still layers an optional session concept (resumability, idle timeout) on top of the wire protocol, which is closer to the older, session-based model the spec deprecated.

**OAuth is a named, deferred fork, not built.** The SDK supports it (`auth=AuthSettings(...)`, `token_verifier=...`) but this server is a local demo, not a service on the public internet — the same call this project's `SPEC.md` already makes for other pieces.

## When per-user rights gating is actually needed: what the SDK gives you, and what it doesn't

Read directly from the installed SDK (`mcp/server/auth/provider.py`, `middleware/bearer_auth.py`, `middleware/auth_context.py`), not assumed — the auth model has two distinct layers, and the gap between them is exactly what a per-user permission design has to fill:

**Layer 1 — the coarse gate, provided.** `RequireAuthMiddleware(app, required_scopes=[...])` checks one fixed list of scopes for an entire ASGI app/mount: "does this bearer token carry everything in `required_scopes` at all?" It runs once per request (stateless — there is no session to check once and reuse), before any tool dispatch, and returns 401/403 with a `WWW-Authenticate` header naming the missing scope. It cannot express "tool A needs `tickets:read`, tool B needs `prs:write`" — one middleware instance, one scope list, applied to everything behind it.

**Layer 2 — the fine-grained check, not provided, yours to write.** Inside any tool handler, `mcp.server.auth.middleware.auth_context.get_access_token()` pulls the current request's `AccessToken` (client_id, scopes, subject, resource, claims) out of a contextvar. This is the hook for anything the blanket middleware can't express — same pattern this project already uses for `allow_side_effects` in `agent/runtime.py`, but keyed off the token instead of a global flag.

What actually needs designing before this is real, in order:

1. **A `TokenVerifier`** — the one piece the SDK does not supply: `async def verify_token(token: str) -> AccessToken | None`. Where a bearer token gets validated (JWT signature check, or introspection against an IdP) and turned into an `AccessToken`.
2. **A scope ↔ domain-right mapping** — e.g. `tickets:read` for `fetch_ticket`, `prs:write` for a future `open_pr`. Nothing in the SDK defines this; it is this project's own decision.
3. **Per-tool enforcement** inside each handler, via `get_access_token()`, checking `.scopes` against what that specific tool needs — Layer 1 alone can't do this.
4. **Resource-level authorization, beyond scopes.** A scope answers "can this token write PRs at all," not "can this user write to *this* target repo." `AccessToken.subject` gives the "who"; the subject → allowed-repos table is not something the SDK provides.
5. **Mono- vs multi-tenant.** One shared MCP server instance (every call re-checks the caller's subject) vs. one instance/config per user (less runtime checking, more infra). Not needed today — `SPEC.md`'s auth model is a single service account, no per-user OAuth — but this is the exact fork that forces the question.

End-to-end, once built: the client sends `Authorization: Bearer <token>` on **every** request (stateless — not once at session start) → `BearerAuthBackend.authenticate()` calls the `TokenVerifier`, checks expiry and, if `resource_server_url` is set, the token's audience (RFC 8707 — was this token minted for *this* server) → `RequireAuthMiddleware` does the one coarse scope check → `get_access_token()` inside a handler does anything finer than that.

## Verified live, with a real MCP client

Started the server, connected with the official SDK's own client (`mcp.client.streamable_http.streamable_http_client` + `mcp.ClientSession`), not a hand-rolled HTTP call:

- `initialize()` — server identifies itself correctly.
- `list_tools()` — returns `fetch_ticket` with the auto-derived input schema `{"issue_id": {"type": "integer"}}`, generated by the SDK from the wrapper function's own type hint (`issue_id: int`), not from `tools/fetch_ticket.py`'s own JSON Schema (that schema is for the Messages API's tool-use protocol; MCP's `@mcp.tool()` decorator derives its own from the Python signature — two different schema mechanisms, deliberately not forced through one path).
- `call_tool("fetch_ticket", {"issue_id": 1})` — real GitHub data back, matching every other verification of this tool in this project.
- `call_tool("fetch_ticket", {"issue_id": 99999})` — `is_error: True`, but the message is a generic `"Error executing tool fetch_ticket"`, not our specific `issue_not_found`. The SDK's default tool-call error handling doesn't forward the raised exception's own message to the client — a reasonable default (don't leak internal error detail to an arbitrary MCP client) left as-is, not overridden.

## Running it

```bash
make mcp-server
# or: uv run --env-file .env python -m agent.mcp_server
```
