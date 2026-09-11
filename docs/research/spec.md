# SPEC — research: execution isolation, GitHub integration

Companion to [`docs/SPEC.md`](../SPEC.md), which describes the current design and what's built. These are the pipeline-level forks named there but not built. (The auth-enforcement gap once tracked here was closed — see `docs/SPEC.md`'s "Out of scope" section and `tools/edit_file.py`'s `_touches_auth_symbol()`.)

## Execution isolation

*Default (POC):* one Docker container running the loop against a per-ticket `git worktree`, runs serialized — the single-worktree limitation is accepted and stated.

*Revisit at production:* per-ticket ephemeral sandboxes/containers behind a root gateway that orchestrates runs, or Claude Managed Agents' hosted sandboxes (a build-vs-buy call for the isolation layer).

*Trigger:* concurrent tickets, or an `edit_file` blast radius we are no longer willing to run in a shared tree.

## GitHub integration

*Default (POC):* hand-written calls for speed. `gh` CLI is not more professional than a typed client — it is a different tradeoff: it inherits `gh auth` and ships fast, but its "schema" becomes a CLI argument surface with weaker validation, subprocess-level testing, and `gh`'s stderr as the error contract.

*Revisit at Day 5 / production:* a typed client (`PyGithub`) or raw REST with an explicit schema, once the tool must survive rate limits, retries, and structured error handling in front of a customer.
