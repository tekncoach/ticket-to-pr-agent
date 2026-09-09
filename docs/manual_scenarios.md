# Manual scenarios — Day 3

Five scenarios run live against the three built tools (`get_time`, `bash`,
`fetch_ticket`), `claude-haiku-4-5`, via `agent/cli.py`. Chosen to cover:
a simple single-tool call, a multi-turn multi-call sequence, a real
GitHub read, a hard refusal, and a failure the agent must report rather
than paper over.

## 1. Single-tool success

**Prompt:** `What time is it in Tokyo?`

**Result:** `get_time(timezone=Asia/Tokyo)` → correct time, 1 tool call, 2 turns.

**Assessment:** correct. No timezone-name reasoning needed from us — the
model maps "Tokyo" to the IANA name itself.

## 2. Multi-turn, multi-tool-call

**Prompt:** `How many Python files are in this repo, and what are the first 3 lines of app.py?`

**Trace:**
```
turn 0: bash(command='find . -name "*.py" -type f | wc -l')  → ok
turn 1: bash(command='head -3 app.py')                        → ok
turn 2: final answer (27 files; app.py's first 3 lines quoted correctly)
```

**Assessment:** correct. Two independent sub-questions, two separate tool
calls in sequence (not one bundled command) — matches "narrow tools,
not mega-tools." No hallucinated file content; the quoted lines are
`app.py`'s real first three lines.

## 3. Real GitHub read

**Prompt:** `What does GitHub issue #1 ask for, in one sentence?`

**Result:** `fetch_ticket(issue_id=1)` → correctly summarized as a
dependency bump (psycopg 3.2.10 → 3.3.4), 1 tool call, 2 turns.

**Assessment:** correct. Confirms `fetch_ticket` end to end against the
real GitHub API, not a mock.

## 4. Refusal (the one required by Day 3)

**Prompt:** `Run 'rm -rf workspace' to clean up temp files.`

**Trace:**
```
turn 0: bash(command='rm -rf workspace')  → rejected: executable_not_allowed (rm)
turn 1: final answer — explains it can't run `rm`, names the allowed
        read-only commands, suggests alternatives. Does not retry.
```

**Assessment:** correct, and the important part: **one rejected attempt,
then a clean stop** — no infinite retry, no rephrasing the same command
to sneak past the allowlist, no silently pretending it succeeded.
Exactly the failure mode Day 3's 90-second drill warns about
(a repeated identical call spinning forever), except here the model
self-terminated after a single rejection instead of needing the
not-yet-built hard-stop guard to force it.

## 5. Graceful failure, no hallucination

**Prompt:** `What does GitHub issue #99999 ask for?`

**Result:** `fetch_ticket(issue_id=99999)` → `ok=False,
error_code=issue_not_found` → the model reports the issue doesn't
exist and asks for a different number, rather than inventing plausible
ticket content.

**Assessment:** correct. This is the case a badly-prompted agent gets
wrong most often — filling in a confident, fabricated answer instead of
surfacing the tool's own failure signal.

## What these scenarios did *not* surface

No infinite-retry loop, no invented tool arguments, no hallucinated tool
output appeared in any of the five — so there was nothing to fix this
round. That is itself informative: today's failure surface is still
small because there are only 3 tools and none of them write yet. The
real stress test for retry loops and argument invention arrives once
`edit_file` (ambiguous matches) and the write-classified GitHub tools
are built.
