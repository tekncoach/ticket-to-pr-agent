"""Unit tests for redact_secrets.

subprocess.run is mocked — these stay hermetic (no betterleaks binary
required in CI) even though the function shells out to a real external
tool at runtime. See docs/SECRETS-REDACTION.md for the live verification
against the real installed binary.
"""
import json
from unittest.mock import MagicMock, patch

from agent.secrets_redaction import REDACTED, redact_secrets


def _mock_betterleaks(findings=None, returncode=None):
    findings = findings or []
    proc = MagicMock()
    proc.returncode = returncode if returncode is not None else (1 if findings else 0)
    proc.stdout = json.dumps(findings)
    return proc


def test_anthropic_key_redacted_by_supplementary_pattern():
    # betterleaks has no rule for this format — the supplementary regex
    # must catch it even if betterleaks itself reports nothing.
    with patch("agent.secrets_redaction.subprocess.run", return_value=_mock_betterleaks([])):
        result = redact_secrets("here is my key sk-ant-fake1234567890fakefake1234567890 in the report")
    assert "sk-ant-" not in result
    assert REDACTED in result


def test_betterleaks_finding_redacted():
    findings = [{"RuleID": "github-fine-grained-pat", "Secret": "github_pat_FAKE1234567890"}]
    with patch("agent.secrets_redaction.subprocess.run", return_value=_mock_betterleaks(findings)):
        result = redact_secrets("token: github_pat_FAKE1234567890 here")
    assert "github_pat_FAKE1234567890" not in result
    assert REDACTED in result


def test_no_findings_leaves_ordinary_text_untouched():
    with patch("agent.secrets_redaction.subprocess.run", return_value=_mock_betterleaks([])):
        result = redact_secrets("just a normal bug report about the sync feature")
    assert result == "just a normal bug report about the sync feature"


def test_missing_binary_degrades_to_supplementary_patterns_only():
    with patch("agent.secrets_redaction.subprocess.run", side_effect=FileNotFoundError):
        result = redact_secrets("sk-ant-fake1234567890fakefake1234567890 and ordinary text")
    # The supplementary pattern still fires even with betterleaks absent —
    # graceful degradation, not a crash.
    assert REDACTED in result
    assert "ordinary text" in result


def test_non_json_output_returns_text_unmodified_rather_than_crashing():
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "not json"
    with patch("agent.secrets_redaction.subprocess.run", return_value=proc):
        result = redact_secrets("ordinary text, no secrets here")
    assert result == "ordinary text, no secrets here"
