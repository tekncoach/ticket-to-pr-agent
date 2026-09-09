"""Unit tests for the edit_file tool's security guards: path confinement,
the denylist, and str_replace's ambiguous-match refusal.

All hermetic — tmp_path stands in for WORKSPACE, no dependency on a real
target repo checkout. No LLM call, no live service, no key required.

Coach's Day 3 review, Top Fix #1: "edit_file's path-escape/denylist/
ambiguous-match logic ... has zero test coverage" and "show me the test
that fails if edit_file's denylist regresses." This is that test.
"""
from unittest.mock import patch

from tools.edit_file import edit_file


def _call(tmp_path, **arguments):
    with patch("tools.edit_file.WORKSPACE", tmp_path):
        return edit_file.handler(arguments)


def test_view_existing_file(tmp_path):
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    result = _call(tmp_path, command="view", path="a.txt")
    assert result.ok
    assert "line1" in result.data


def test_path_traversal_rejected(tmp_path):
    result = _call(tmp_path, command="view", path="../../etc/passwd")
    assert not result.ok
    assert result.error_code == "path_escapes_workspace"


def test_absolute_path_outside_workspace_rejected(tmp_path):
    result = _call(tmp_path, command="view", path="/etc/passwd")
    assert not result.ok
    assert result.error_code == "path_escapes_workspace"


def test_denylist_file_rejected(tmp_path):
    result = _call(tmp_path, command="view", path="crypto.py")
    assert not result.ok
    assert result.error_code == "path_denied"


def test_denylist_directory_rejected(tmp_path):
    result = _call(tmp_path, command="view", path="migrations/0001_init.sql")
    assert not result.ok
    assert result.error_code == "path_denied"


def test_str_replace_ambiguous_match_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("foo\nfoo\n")
    result = _call(tmp_path, command="str_replace", path="a.txt", old_str="foo", new_str="bar")
    assert not result.ok
    assert result.error_code == "ambiguous_match"
    # The file must be untouched when the match was rejected as ambiguous.
    assert (tmp_path / "a.txt").read_text() == "foo\nfoo\n"


def test_str_replace_string_not_found(tmp_path):
    (tmp_path / "a.txt").write_text("foo\n")
    result = _call(tmp_path, command="str_replace", path="a.txt", old_str="zzz", new_str="bar")
    assert not result.ok
    assert result.error_code == "string_not_found"


def test_str_replace_succeeds_on_unique_match(tmp_path):
    (tmp_path / "a.txt").write_text("foo\nbar\n")
    result = _call(tmp_path, command="str_replace", path="a.txt", old_str="foo", new_str="baz")
    assert result.ok
    assert (tmp_path / "a.txt").read_text() == "baz\nbar\n"


def test_create_backs_up_existing_file(tmp_path):
    (tmp_path / "a.txt").write_text("old content\n")
    result = _call(tmp_path, command="create", path="a.txt", file_text="new content\n")
    assert result.ok
    assert (tmp_path / "a.txt").read_text() == "new content\n"
    assert (tmp_path / "a.txt.bak").read_text() == "old content\n"


def test_view_missing_file_returns_not_found(tmp_path):
    result = _call(tmp_path, command="view", path="nope.txt")
    assert not result.ok
    assert result.error_code == "not_found"


def test_insert_at_line_zero(tmp_path):
    (tmp_path / "a.txt").write_text("line1\nline2\n")
    result = _call(tmp_path, command="insert", path="a.txt", insert_line=0, insert_text="line0")
    assert result.ok
    assert (tmp_path / "a.txt").read_text().splitlines()[0] == "line0"
