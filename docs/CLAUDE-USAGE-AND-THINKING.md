# Anthropic Messages API — usage object & thinking

Reference for what `response.usage` actually contains, and how the `thinking` request param works. Verified by inspecting two real live calls (`resp.usage.model_dump()`), not recalled from memory — see the raw output below.

## Full `usage` object, verified live

```json
{
  "cache_creation": {
    "ephemeral_1h_input_tokens": 0,
    "ephemeral_5m_input_tokens": 0
  },
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "inference_geo": "not_available",
  "input_tokens": 15,
  "output_tokens": 8,
  "output_tokens_details": null,
  "server_tool_use": null,
  "service_tier": "standard"
}
```

Captured from a plain call with no `thinking`, no caching, no server tools — this is the baseline shape every response carries, most fields empty because nothing exercised them.

## What each field means, and whether it matters here

| Field | What it is | Worth logging for this project? |
|---|---|---|
| `input_tokens` / `output_tokens` | Billed token counts for the request/response | Yes — already logged |
| `output_tokens_details.thinking_tokens` | Thinking tokens, **included within** `output_tokens`, not additive | Yes — see Thinking below |
| `cache_creation_input_tokens` / `cache_read_input_tokens` | Prompt-caching token counts | Yes, logged at 0 today — no `cache_control` breakpoints anywhere yet, despite the system prompt + tool schemas being identical every turn of a run: a real, unexploited caching opportunity |
| `cache_creation.ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens` | Breakdown of cache-creation tokens by TTL | No — only meaningful once actually using 1h/5m cache breakpoints |
| `inference_geo` | Where inference ran, if `inference_geo` was set on the request | No — we never set that param, always `"not_available"` |
| `server_tool_use` | Usage from server-side tools (`web_search`, `code_execution`, ...) | No — we use no server-side tools |
| `service_tier` | Which tier billed the request (`standard`, priority, ...) | Yes, cheap to log — would change the moment Priority Tier is ever used |

Response-level fields (`resp.*`, not under `usage`) worth the same treatment:

| Field | What it is | Worth logging? |
|---|---|---|
| `resp.id` | Unique message id for this API call | Yes — for referencing a specific call in support/debugging |
| `resp.model` | The actual pinned snapshot Anthropic used (e.g. `claude-haiku-4-5-20251001`) | Yes — **differs from the alias you request** (`claude-haiku-4-5`); more precise for reproducibility than the alias alone |
| `resp.stop_details` | Populated **only** when `stop_reason == "refusal"` (category + explanation) | Yes — without it, a refusal looks like an unremarkable final answer with no record of why |
| `resp.container`, `resp.stop_sequence`, `resp.role`, `resp.type` | Constant or null unless using code-execution containers / custom stop sequences | No — nothing to observe until those features are in use |

## Thinking: two incompatible request shapes

Sending the wrong shape for the model in use is a 400, not a silent fallback.

| Model family | `thinking` param | Notes |
|---|---|---|
| Opus 5, Sonnet 5, Fable 5 / 5.1 | `{"type": "adaptive"}` | `budget_tokens` rejected outright; thinking is on by default for these even if you omit the param entirely |
| Everything else — Haiku 4.5 (this project's default) included | `{"type": "enabled", "budget_tokens": N}` | `budget_tokens` required: minimum 1024, and strictly less than `max_tokens` (room must remain for the actual answer after thinking) |

Billing: thinking tokens are **included in `output_tokens`**, not billed separately — `output_tokens_details.thinking_tokens` is a breakdown for observability, not an extra cost line.

Verified live, thinking enabled on Haiku 4.5 (`{"type": "enabled", "budget_tokens": 1024}`, `max_tokens=1200`):

```json
{
  "input_tokens": 49,
  "output_tokens": 276,
  "output_tokens_details": {
    "thinking_tokens": 138
  }
}
```

`resp.content` also gains a `"thinking"` block type alongside the usual `"text"` block — the existing `final_text` extraction (`"".join(block.text for block in resp.content if block.type == "text")`) already skips it correctly, since a thinking block has no `.text` attribute the filter would match.

Multi-turn continuation: echo `resp.content` back into `messages` verbatim on every turn regardless of thinking (already this project's pattern) — thinking blocks must be preserved unchanged when continuing on the same model, and this project already does that by construction.

## Used in this repo

`agent/runtime.py`'s `ADAPTIVE_THINKING_MODELS` set picks the correct shape automatically from `self.model`. `AgentRuntime.thinking_enabled` (env `THINKING_ENABLED`, default `false`) turns it on; `thinking_budget_tokens` (env `THINKING_BUDGET_TOKENS`, default 2048) only matters on the budget_tokens path. `__post_init__` validates the budget_tokens/max_tokens relationship eagerly rather than surfacing a 400 mid-run.

## Verify this yourself

Cached prices and behavior — re-check before trusting this file if it's more than a few months old:

- https://platform.claude.com/docs/en/build-with-claude/extended-thinking.md
- https://platform.claude.com/docs/en/api/messages (response shape, `usage` object)
