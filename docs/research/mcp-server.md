# MCP server — research: per-user rights gating

Companion to [`docs/MCP-SERVER.md`](../MCP-SERVER.md), which describes what's actually built (`fetch_ticket` exposed over MCP, no auth — a local demo). This file is the design work for the fork named there but not built: real per-user permission gating.

## What the SDK gives you, and what it doesn't

Read directly from the installed SDK (`mcp/server/auth/provider.py`, `middleware/bearer_auth.py`, `middleware/auth_context.py`), not assumed — the auth model has two distinct layers, and the gap between them is exactly what a per-user permission design has to fill:

**Layer 1 — the coarse gate, provided.** `RequireAuthMiddleware(app, required_scopes=[...])` checks one fixed list of scopes for an entire ASGI app/mount: "does this bearer token carry everything in `required_scopes` at all?" It runs once per request (stateless — there is no session to check once and reuse), before any tool dispatch, and returns 401/403 with a `WWW-Authenticate` header naming the missing scope. It cannot express "tool A needs `tickets:read`, tool B needs `prs:write`" — one middleware instance, one scope list, applied to everything behind it.

**Layer 2 — the fine-grained check, not provided, yours to write.** Inside any tool handler, `mcp.server.auth.middleware.auth_context.get_access_token()` pulls the current request's `AccessToken` (client_id, scopes, subject, resource, claims) out of a contextvar. This is the hook for anything the blanket middleware can't express — same pattern this project already uses for `allow_side_effects` in `agent/runtime.py`, but keyed off the token instead of a global flag.

## What actually needs designing before this is real

1. **A `TokenVerifier`** — the one piece the SDK does not supply: `async def verify_token(token: str) -> AccessToken | None`. Where a bearer token gets validated (JWT signature check, or introspection against an IdP) and turned into an `AccessToken`.
2. **A scope ↔ domain-right mapping** — e.g. `tickets:read` for `fetch_ticket`, `prs:write` for a future `open_pr`. Nothing in the SDK defines this; it is this project's own decision.
3. **Per-tool enforcement** inside each handler, via `get_access_token()`, checking `.scopes` against what that specific tool needs — Layer 1 alone can't do this.
4. **Resource-level authorization, beyond scopes.** A scope answers "can this token write PRs at all," not "can this user write to *this* target repo." `AccessToken.subject` gives the "who"; the subject → allowed-repos table is not something the SDK provides.
5. **Mono- vs multi-tenant.** One shared MCP server instance (every call re-checks the caller's subject) vs. one instance/config per user (less runtime checking, more infra). Not needed today — `SPEC.md`'s auth model is a single service account, no per-user OAuth — but this is the exact fork that forces the question.

## End-to-end, once built

The client sends `Authorization: Bearer <token>` on **every** request (stateless — not once at session start) → `BearerAuthBackend.authenticate()` calls the `TokenVerifier`, checks expiry and, if `resource_server_url` is set, the token's audience (RFC 8707 — was this token minted for *this* server) → `RequireAuthMiddleware` does the one coarse scope check → `get_access_token()` inside a handler does anything finer than that.

**Trigger to revisit:** real per-user OAuth is ever actually needed — today's auth model is a single service account, named in `docs/SPEC.md`.
