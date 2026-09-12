# agent/secrets_redaction.py
#
# Redacts secret-shaped substrings from untrusted external content (a
# fetched GitHub Issue body, for instance) BEFORE it flows anywhere else —
# into the model's context, into the persisted JSONL trace, into a final
# answer. One redaction point, same "confine the risk at the boundary"
# pattern already used for edit_file's path denylist.
#
# Shells out to betterleaks (an external Go binary, not a Python package —
# install separately: `brew install betterleaks`), not detect-secrets: the
# first choice here was detect-secrets, reversed after checking — its last
# release was May 2024, and testing it directly (not assumed) showed real
# gaps: no rule for GitHub's current fine-grained github_pat_ format, and
# its analyze_string() only returns an internal regex capture group for
# some plugins (GitHubTokenDetector's own analyze_string() returned just
# "ghp", not the full token). betterleaks — maintained by gitleaks' own
# creators as its stated successor ("gitleaks is feature complete") — has
# a github-fine-grained-pat rule natively, and its JSON report's `Secret`
# field is the exact matched string, no capture-group ambiguity.
#
# Still, no rule anywhere for Anthropic's sk-ant- key format (checked by
# testing, not assumed) — supplemented by hand below.
#
# Pattern matching is a guess about what a secret looks like. The credentials
# we hold are not a guess, so they are scrubbed by value first: an API that
# echoes a token back in an error message ("token <x> is malformed") defeats
# every shape-based rule, and our own token is the one secret guaranteed to
# be in reach of anything we log.
#
# GitHub itself already scans issue bodies/comments for secrets (free on
# public repos), but that's a platform-side notification to the secret's
# owner, not an API we can call before OUR OWN pipeline ingests the same
# content — this redaction step is a separate, necessary layer regardless.
from __future__ import annotations

import json
import os
import re
import subprocess

REDACTED = "[REDACTED_SECRET]"

# betterleaks has no rule for this format — confirmed by testing, not
# assumed. github_pat_ needs no equivalent entry: betterleaks' own
# github-fine-grained-pat rule already covers it natively.
_SUPPLEMENTARY_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
]

_BETTERLEAKS_TIMEOUT_S = 10

# Env vars holding a credential this process actually carries. Anything short
# is a placeholder or an accident, and substituting it would blank out
# ordinary text — an empty value must never turn into a match-everything rule.
_CREDENTIAL_ENV_VARS = ("GITHUB_TOKEN", "LLM_API_KEY", "ANTHROPIC_API_KEY", "HF_TOKEN")
_MIN_CREDENTIAL_LENGTH = 8


def _redact_known_credentials(text: str) -> str:
    for name in _CREDENTIAL_ENV_VARS:
        value = os.environ.get(name, "")
        if len(value) >= _MIN_CREDENTIAL_LENGTH and value in text:
            text = text.replace(value, REDACTED)
    return text


def redact_secrets(text: str) -> str:
    """Replace every secret-shaped substring in text with a placeholder.

    Applied to untrusted external content before it reaches the model, the
    trace log, or a final answer.
    """
    text = _redact_known_credentials(text)

    for pattern in _SUPPLEMENTARY_PATTERNS:
        text = pattern.sub(REDACTED, text)

    try:
        proc = subprocess.run(
            ["betterleaks", "stdin", "--report-format", "json",
             "--report-path", "-", "--no-banner"],
            input=text,
            capture_output=True,
            text=True,
            timeout=_BETTERLEAKS_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # betterleaks not installed, or hung — degrade to the supplementary
        # patterns only, rather than crashing fetch_ticket over a missing
        # optional binary. Named gap: this silently narrows coverage if the
        # binary is absent; revisit if that's ever seen in practice (e.g.
        # log a warning the first time it happens).
        return text

    # betterleaks' own convention: exit 1 means "leaks found", not an
    # error. 0 means none found. Anything else is a real failure.
    if proc.returncode not in (0, 1):
        return text

    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return text

    for finding in findings:
        secret = finding.get("Secret")
        if secret:
            text = text.replace(secret, REDACTED)

    return text
