# Secrets redaction — research: the betterleaks binary in CI and Docker

Companion to [`docs/SECRETS-REDACTION.md`](../SECRETS-REDACTION.md), which describes what's built (`agent/secrets_redaction.py` shells out to `betterleaks`, a local binary) and its environment-by-environment status table.

**Default (POC):** installed locally by hand (`brew install betterleaks`); absent in CI (tests mock the subprocess call) and in the Docker image (does not exist yet). If the binary is missing at runtime, redaction silently narrows to one hand-rolled pattern instead of failing the fetch.

**Revisit when the image is built:** copy the binary into the image (multi-stage build from `ghcr.io/betterleaks/betterleaks`, or a pinned binary download) as part of packaging the service; add it to the CI job once that's done, so the real binary path is actually exercised somewhere, not only the degraded one.

**Trigger:** deployment being built out, or the degraded path ever firing in a way that matters.
