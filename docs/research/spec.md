# SPEC — research: execution isolation, GitHub integration, auth enforcement

Companion to [`docs/SPEC.md`](../SPEC.md), which describes the current design and what's built. These are the pipeline-level forks named there but not built.

## Execution isolation

*Default (POC):* one Docker container running the loop against a per-ticket `git worktree`, runs serialized — the single-worktree limitation is accepted and stated.

*Revisit at production:* per-ticket ephemeral sandboxes/containers behind a root gateway that orchestrates runs, or Claude Managed Agents' hosted sandboxes (a build-vs-buy call for the isolation layer).

*Trigger:* concurrent tickets, or an `edit_file` blast radius we are no longer willing to run in a shared tree.

## GitHub integration

*Default (POC):* hand-written calls for speed. `gh` CLI is not more professional than a typed client — it is a different tradeoff: it inherits `gh auth` and ships fast, but its "schema" becomes a CLI argument surface with weaker validation, subprocess-level testing, and `gh`'s stderr as the error contract.

*Revisit at Day 5 / production:* a typed client (`PyGithub`) or raw REST with an explicit schema, once the tool must survive rate limits, retries, and structured error handling in front of a customer.

## Auth enforcement gap in `edit_file`'s denylist

Auth logic lives inside `app.py`, shared with unrelated code — there is no dedicated auth file a path-level denylist can isolate, so "no auth changes" is a prompt instruction today, not an enforced boundary (the gap `docs/SPEC.md`'s own rule — a suggestion isn't a boundary — says not to trust).

*Revisit:* once auth logic is extracted to its own module, or `edit_file` gets a line-range or symbol-level guard. Neither built.
