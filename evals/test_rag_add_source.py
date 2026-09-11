"""Unit tests for rag/add_source.py — the manifest-registration CLI.
embed_and_upsert is mocked (no embedding call, no key needed); chunk_file
runs for real against a tiny local file, no network involved either way.
"""
import json
import sys
from unittest.mock import patch

import pytest

from rag import add_source


def _run(argv):
    with patch.object(sys, "argv", ["add_source.py"] + argv):
        add_source.main()


def test_unreviewed_entry_is_recorded_but_not_ingested(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(add_source, "MANIFEST_PATH", manifest_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\ncontent")

    with patch.object(add_source, "embed_and_upsert") as mock_embed:
        _run([str(doc), "--license", "test"])

    manifest = json.loads(manifest_path.read_text())
    assert len(manifest) == 1
    assert manifest[0]["pii_reviewed"] is False
    mock_embed.assert_not_called()


def test_reviewed_entry_is_ingested(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(add_source, "MANIFEST_PATH", manifest_path)
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\ncontent")

    with patch.object(add_source, "embed_and_upsert", return_value=3) as mock_embed:
        _run([str(doc), "--license", "test", "--reviewed"])

    manifest = json.loads(manifest_path.read_text())
    assert manifest[0]["pii_reviewed"] is True
    mock_embed.assert_called_once()


def test_missing_file_rejected(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(add_source, "MANIFEST_PATH", manifest_path)
    with pytest.raises(SystemExit):
        _run([str(tmp_path / "nope.md"), "--license", "test"])
    assert not manifest_path.exists()


def test_duplicate_path_rejected(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(add_source, "MANIFEST_PATH", manifest_path)
    doc = tmp_path / "doc.md"
    doc.write_text("content")

    with patch.object(add_source, "embed_and_upsert"):
        _run([str(doc), "--license", "test"])
    with pytest.raises(SystemExit):
        _run([str(doc), "--license", "test"])

    # Rejected before a second entry was ever appended.
    assert len(json.loads(manifest_path.read_text())) == 1


def test_license_is_required(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(add_source, "MANIFEST_PATH", manifest_path)
    doc = tmp_path / "doc.md"
    doc.write_text("content")
    with pytest.raises(SystemExit):
        _run([str(doc)])
