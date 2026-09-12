# Resilience — what happens when a tool fails

Every number and every outcome below was observed by running the failure against the real code, not reasoned about. The chaos checks that produced them are described at the end.

## The taxonomy is the contract

`agent/errors.py` gives every failure, HTTP or local, one of eight classes. The wire form is `"<class>: <detail>"`, so `ToolResult.error_code` stays a string and the part before the colon comes from a closed set.

| Class | Means | Retried |
|---|---|---|
| `auth` | no credentials, or they were rejected | no |
| `denied` | authenticated, but not allowed — a policy refusal | **no, deliberately** |
| `not_found` | the thing is not there | no |
| `validation` | the request itself is malformed | no |
| `rate_limit` | 429, or a 403 carrying `Retry-After` | yes |
| `unavailable` | 5xx, connection reset, DNS failure | yes |
| `timeout` | the call did not come back | yes |
| `internal` | a bug on our side | no |

Two defaults carry weight. **`denied` is never retried**: a policy refusal is a correct, final answer, and retrying one is how a guard gets worn down into a suggestion. **An unrecognised code classifies as `internal`**, so a tool added later whose author never read that file cannot accidentally acquire an infinite retry loop.

## Retry policy

`tools/http_client.py`, 4 attempts, equal jitter — half the delay fixed so it always backs off, half random so callers that failed together do not retry in lockstep. `Retry-After` overrides the computed delay whenever the server sends one, capped at 60s.

Measured end to end, four failing attempts with real sleeps: **2.44s** wall clock.

**Retries are restricted to idempotent methods** (`GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`). Anything else needs an idempotency key before this layer will repeat it, and when it refuses the error says so rather than looking like a hard failure:

```
unavailable: HTTP 500 (not retried: POST without an idempotency key)
```

## Idempotency: two mechanisms, and why both exist

**The key itself** — `idempotency_key(actor, action, payload)`, SHA-256 of the sorted JSON, truncated to 32 chars. The same intent hashes to the same key however many times it is asked for; a different issue, body, or action hashes differently. The `actor` is the target repo, not a user: this is a service account with no per-user identity ([`docs/SPEC.md`](SPEC.md), Auth model).

Passing it to `ResilientClient.request()` sends it as an `Idempotency-Key` header **and** is what unlocks retrying a write. That path is implemented and tested.

**But it only makes a write safe if the server honours the header, and GitHub does not.** Checked against the REST documentation for `POST /repos/{owner}/{repo}/issues/{n}/comments`: no `Idempotency-Key`, no deduplication of identical bodies. It is a Stripe idiom, not an HTTP one. Retrying a POST to GitHub because a key was attached would produce exactly the duplicate the key appears to prevent.

So `tools/comment_on_ticket.py` **withholds the key from the transport on purpose** — the POST is sent at most once per cycle — and enforces idempotency itself:

1. The key rides in the comment body as an HTML comment, invisible when GitHub renders it. The posted comment is its own record; there is no local state to keep in sync with a remote one.
2. Every cycle reads the issue's comments before writing, and stops if the marker is already there.
3. The retry loop wraps the **whole read-then-write cycle**, not the POST.

Point 3 is what survives the case a transport retry cannot: GitHub accepts the comment, the connection drops before the response arrives, the call reports failure. A transport retry reposts blind. Here the next cycle's read finds the marker and stops.

**Known limit:** the marker search reads one page of 100 comments. A very busy issue could push the marker out of that window; the cost is one duplicate comment, not a wrong action.

## Dry run

`comment_on_ticket` does everything except the write — duplicate check included — so the receipt describes what would actually happen rather than what the caller hopes. `SHADOW_MODE=true` forces it, which makes it a second lock: opening the runtime's write gate is not on its own enough to start posting to a real repo.

## Receipts

```
commented on tekncoach/liberty-rider-myroadtrips#42 (comment 100): https://github.com/…
already commented on tekncoach/liberty-rider-myroadtrips#42 (comment 100) — no duplicate posted: https://…
would comment on tekncoach/liberty-rider-myroadtrips#42 (SHADOW_MODE, nothing posted): CI is green.
```

## Chaos checks — observed behaviour

Each failure was injected through `httpx.MockTransport` against the real tools. `req` counts actual HTTP requests made.

| Injected failure | Result | Class | Retried | Requests |
|---|---|---|---|---|
| Connection reset, every attempt | fail | `unavailable` | yes | 4 |
| Timeout, every attempt | fail | `timeout` | yes | 4 |
| Token revoked → 401 | fail | `auth` | no | 1 |
| No write permission → 403 | fail | `denied` | no | 1 GET + 1 POST |
| Invalid issue id → 404 (read) | fail | `not_found` | no | 1 |
| Invalid issue id → 404 (write) | fail | `not_found` | no | 1 GET + 1 POST |
| 429 ×2 with `Retry-After`, then 200 | **ok** | — | yes | 3 |
| Secondary rate limit: 403 + `Retry-After` | fail | `rate_limit` | yes | 4 |
| Write lands, response lost | **ok, 1 comment** | — | cycle re-read | 3 |
| 4× 503, real sleeps | fail | `unavailable` | yes | 4, 2.44s |

Two things the table is worth reading for.

**The secondary rate limit is classified `rate_limit`, not `denied`.** GitHub signals it as a 403 carrying `Retry-After`, and that header is the only thing separating it from a permissions refusal. Without the distinction, every secondary limit would read as "not allowed" and never retry.

**A write costs two API calls**, one read and one write, because the read is the idempotency guard. That is the price of not having a server-side key, and it is worth naming against GitHub's rate limits.

### The bug the chaos checks found

Everything above passed on the first run except one case, which was not in any test: **every read failing while every write lands and loses its response.** The tool posted **three comments**.

`_find_marked_comment` returned `None` both for "no marker is there" and for "the read failed", and the caller read the second as the first. Two different answers collapsed into one value, and the unsafe direction was the default.

Fixed: a write only happens on positive knowledge that no marker exists. Once a POST has been sent, an unconfirmable read stops the tool and names the issue to check:

```
unavailable: a comment was sent to <repo>#42 but could not be confirmed;
not reposting, check the issue
```

That can leave a comment unconfirmed. Posting again duplicates it for certain — and of the two outcomes, only one is recoverable by a human opening the issue. The first read is exempt: nothing has been sent, so there is nothing to duplicate.

Both directions are frozen as regression tests in `evals/test_comment_on_ticket_tool.py`.

## Conversation-level recovery

Three ways a run stops before `MAX_TURNS`, each ending in a sentence rather than a code.

**An identical tool call, repeated.** Already there before today: same tool, same arguments, so the outcome is already known. Hard stop.

**An `auth` failure, on the first occurrence.** No other tool is tried. An auth failure is neither transient nor something the agent can route around, so handing it back to the model only buys creative workarounds for a problem a human fixes in a minute — if they are told about it:

```
Stopping: fetch_ticket could not authenticate (auth: HTTP 401). I did not try
anything else — the credentials need renewing or their permissions widening,
I cannot work around this.
```

**Two consecutive failures of the same tool.** Consecutive and per tool, both deliberate: an agent that fails, corrects its arguments and succeeds is doing exactly what it should, and a threshold that counted total failures would cut off the self-correction it exists to encourage. A success resets the streak.

```
Stopping: comment_on_ticket failed 2 times in a row, last with
rate_limit: HTTP 429 after 4 attempts. Trying again is not making progress —
wait for the rate-limit window to reset, then run this ticket again.
```

The suggested next step comes from the error class (`agent/errors.py`, `next_step()`), so every class has one and none is improvised. The typed code stays in the sentence: the person reading it may be the one grepping the logs.

## The LLM call

Corrected after checking rather than assuming: **the Anthropic SDK already retries 429s and 5xx itself**, twice by default, with backoff, honouring `retry-after`. This project had been relying on that without saying so; `LLM_MAX_RETRIES` now states it in the file that depends on it.

By the time an `anthropic.APIError` reaches our handler those attempts are spent, which is why the handler stops rather than trying again. It classifies the exception onto the same taxonomy and produces the same shape of sentence:

```
Stopping: the model call failed (rate_limit: RateLimitError), after the SDK's
own 2 retries — wait for the rate-limit window to reset, then run this ticket
again.
```

## What the agent is told

Everything above is the runtime speaking when it gives up. A tool that fails once while the run continues is the model's to handle, so `SYSTEM_PROMPT` carries the taxonomy: read the class rather than guessing from the wording, treat `auth` and `denied` as final and do not route around them, do not immediately repeat a transient failure that was already retried, fix arguments once on `validation` or `not_found`, never report a success it did not observe, and when it cannot finish, say what stopped it and the one thing a person should do next.

A test asserts every class the code can emit is named there, so the prompt cannot drift away from the taxonomy it describes.

## Not done

**Nothing resumes.** A run that stops for any of the reasons above starts from scratch when re-run. Work already done — an edit made, a comment posted — is re-derived rather than picked up.
