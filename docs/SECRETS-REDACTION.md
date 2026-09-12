# Secrets redaction

`agent/secrets_redaction.py` scrubs secret-shaped substrings out of untrusted external content — a fetched GitHub Issue body, specifically — before it reaches the model, the persisted JSONL trace, or a final answer. One redaction point, the same "confine the risk at the boundary" pattern already used for `edit_file`'s path denylist.

## Why this exists, distinct from the earlier GITHUB_TOKEN test

`evals/test_no_secrets_in_logs.py` (an earlier fix) asserts *our own* `GITHUB_TOKEN` never leaks into a tool's output. This is a different, larger concern: a GitHub Issue is written by anyone, and its body is untrusted input — someone could paste a real API key into a bug report as a repro example. GitHub itself already scans issue bodies and comments for secrets (free on public repos), but that's a platform-side notification to the secret's *owner* — not an API this project can call before its own pipeline ingests the same content. This redaction step is necessary regardless of what GitHub's own scanning does on its side.

## Why betterleaks, not detect-secrets

detect-secrets (Yelp) was the first choice, reversed after testing it directly rather than trusting its reputation:

- Its last release was May 2024 — over two years stale as of this project.
- Its `GitHubTokenDetector` only matches the classic `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` format (36 characters) — **not** GitHub's current fine-grained `github_pat_` format, which is what this project's own `GITHUB_TOKEN` actually uses.
- Its `analyze_string()` method doesn't reliably return the full matched secret for every plugin — for `GitHubTokenDetector` specifically, it returned only the internal regex capture group (`"ghp"`), not the token, making it unusable for redaction (replacing the found substring) without bypassing the library's own intended API and reaching into its compiled regexes directly.

betterleaks — maintained by gitleaks' own creators as gitleaks' stated successor ("gitleaks is feature complete, I'm not merging new features into it") — has a `github-fine-grained-pat` rule natively, and its JSON report's `Secret` field is the exact matched string with no capture-group ambiguity. Verified directly: piped a sample containing a classic token, a fine-grained `github_pat_`, and a fake Anthropic key through `betterleaks stdin --report-format json --report-path -` — the first two were found and returned cleanly; the Anthropic key was not (see below).

**Real gap, confirmed by testing, not assumed:** no rule anywhere covers Anthropic's `sk-ant-` key format. Supplemented in code with one hand-rolled pattern.

## Architecture: an external binary, not a Python package

betterleaks is a compiled Go binary — `uv add` cannot install it. `redact_secrets()` shells out to it via `subprocess`, piping text over stdin and reading its JSON report back. This has real consequences across every environment that needs the real (not degraded) behavior:

| Environment | Status |
|---|---|
| Local dev | Requires `brew install betterleaks` (or the Linux equivalent) — a prerequisite now documented in the README's Quickstart, not assumed. |
| CI (`.github/workflows/ci.yml`) | betterleaks is **not installed**. `evals/test_secrets_redaction.py` mocks `subprocess.run`, so CI stays hermetic and green — but it only exercises the graceful-degradation path (the supplementary `sk-ant-` pattern), never the real binary. Named gap, not hidden. |
| Docker (not built yet) | See [`docs/research/secrets-redaction.md`](research/secrets-redaction.md): the image will need betterleaks copied in (multi-stage build from `ghcr.io/betterleaks/betterleaks`, or a pinned binary download) — not designed in detail until deployment is actually built out. |

**Graceful degradation, on purpose:** if the binary is missing or hangs, `redact_secrets()` falls back to the supplementary regex pattern only, rather than crashing `fetch_ticket`. This means a misconfigured environment silently gets narrower protection instead of failing loudly — a real, named tradeoff, not an oversight. Revisit (e.g. log a warning) if that's ever actually hit in practice.

## Verified live, with the real installed binary

```
$ printf '...ghp_a1B2...\n...github_pat_11AAA...\n...sk-ant-api03-fake...\n' | \
    betterleaks stdin --report-format json --report-path - --no-banner
```

Returned two findings (`github-pat`, `github-fine-grained-pat`), each with a `Secret` field matching the exact substring. The Anthropic key was absent from betterleaks' own output, confirmed caught instead by the supplementary pattern when run through `agent.secrets_redaction.redact_secrets()` directly — all three placeholders replaced, ordinary surrounding text untouched.
