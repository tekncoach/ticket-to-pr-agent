"""Unit tests for open_pr. Hermetic — git is mocked at the subprocess level
and GitHub answers through httpx.MockTransport, so nothing is committed,
nothing is pushed, and no repository is touched.

Two properties carry the weight: the agent's own .bak files never reach a
pull request, and the token never reaches a result.
"""
from unittest.mock import patch

import httpx
import pytest

from tools.http_client import ResilientClient
from tools.open_pr import branch_for, open_pr

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"
PORCELAIN = " M app.py\n M db.py\n?? tests/test_new.py\n"


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    """Writes enabled by default; the shadow-mode test opts back out."""
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("SHADOW_MODE", "false")


class FakeGit:
    """Records every git invocation and answers each one successfully unless
    a failure is queued for a specific subcommand."""

    def __init__(self, porcelain=PORCELAIN, fail_on=None, fail_stderr=""):
        self.calls = []
        self._porcelain = porcelain
        self._fail_on = fail_on
        self._fail_stderr = fail_stderr

    def __call__(self, args, **kwargs):
        # subprocess is one module object shared with agent.secrets_redaction,
        # so patching it here also intercepts betterleaks. Answer that one as
        # "no findings" and keep it out of the recorded git calls.
        if not args or args[0] != "git":
            return _completed(0, stdout="[]")
        self.calls.append(args)
        if args[1:3] == ["status", "--porcelain"]:
            return _completed(0, stdout=self._porcelain)
        # Matched against the whole argv: the commit call carries `-c key=value`
        # pairs before its subcommand.
        if self._fail_on and self._fail_on in args:
            return _completed(1, stderr=self._fail_stderr)
        return _completed(0)

    def staged(self):
        add = next((c for c in self.calls if "add" in c), None)
        return [] if add is None else list(add[add.index("--") + 1:])

    def ran(self, subcommand):
        return any(subcommand in c for c in self.calls)


def _completed(returncode, stdout="", stderr=""):
    import subprocess
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeGitHub:
    def __init__(self, existing_pulls=(), create_response=None):
        self.requests = []
        self._existing = list(existing_pulls)
        self._create = create_response or httpx.Response(
            201, json={"number": 7, "html_url": "https://github.com/o/r/pull/7"},
        )

    def handler(self, request):
        self.requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=self._existing)
        return self._create


def _call(arguments, git=None, github=None):
    git = git or FakeGit()
    github = github or FakeGitHub()

    def build(token):
        return ResilientClient(
            "https://api.github.com", token, transport=httpx.MockTransport(github.handler),
        )

    with patch("tools.open_pr.subprocess.run", side_effect=git), \
         patch("tools.open_pr._build_client", build), \
         patch("tools.http_client.time.sleep"):
        return open_pr.handler(arguments), git, github


def test_opens_a_draft_pr_and_returns_a_readable_receipt():
    result, git, github = _call({"issue_id": 13, "title": "Add the share link"})
    assert result.ok
    assert result.data.startswith("opened draft PR #7 for issue #13")
    assert "3 file(s) changed" in result.data
    assert "https://github.com/o/r/pull/7" in result.data

    created = [r for r in github.requests if r.method == "POST"]
    assert len(created) == 1
    import json
    body = json.loads(created[0].content)
    assert body["draft"] is True, "a human reviews before anything merges"
    assert body["head"] == "agent/issue-13"
    assert body["base"] == "main"
    assert "Closes #13" in body["body"]


def test_the_agents_own_backup_files_never_reach_the_pr():
    # edit_file writes <file>.bak beside everything it overwrites, and the
    # target repo does not ignore them. `git add -A` would ship the agent's
    # backups as part of the change.
    git = FakeGit(porcelain=" M app.py\n?? app.py.bak\n?? db.py.bak\n M db.py\n")
    result, git, _ = _call({"issue_id": 13, "title": "t"}, git=git)
    assert result.ok
    assert git.staged() == ["app.py", "db.py"]
    assert not any(p.endswith(".bak") for p in git.staged())


def test_a_renamed_file_is_staged_under_its_new_path():
    git = FakeGit(porcelain='R  old.py -> new.py\n')
    _, git, _ = _call({"issue_id": 13, "title": "t"}, git=git)
    assert git.staged() == ["new.py"]


def test_the_branch_is_derived_from_the_issue_so_it_is_stable():
    # This is the idempotency key: same intent, same head branch, and the
    # existing-PR lookup can therefore be trusted.
    assert branch_for(13) == "agent/issue-13"
    assert branch_for(13) == branch_for(13)
    assert branch_for(13) != branch_for(14)


def test_an_existing_pr_is_reported_rather_than_duplicated():
    github = FakeGitHub(existing_pulls=[
        {"number": 4, "html_url": "https://github.com/o/r/pull/4"},
    ])
    result, git, github = _call({"issue_id": 13, "title": "t"}, github=github)
    assert result.ok
    assert result.data.startswith("pull request already open for issue #13 (#4)")
    assert "no duplicate created" in result.data
    assert not any(r.method == "POST" for r in github.requests)
    assert not git.ran("push"), "nothing is pushed when the PR already exists"


def test_a_clean_working_tree_is_refused_before_anything_happens():
    git = FakeGit(porcelain="")
    result, git, github = _call({"issue_id": 13, "title": "t"}, git=git)
    assert result.error_code == "validation: the working tree has no changes to open a PR for"
    assert not git.ran("commit")
    assert not github.requests


def test_shadow_mode_describes_the_push_without_making_it(monkeypatch):
    monkeypatch.setenv("SHADOW_MODE", "true")
    result, git, github = _call({"issue_id": 13, "title": "t"})
    assert result.ok
    assert result.data.startswith("would open a draft PR from agent/issue-13 into main")
    assert "SHADOW_MODE" in result.data
    assert "app.py" in result.data
    assert not git.ran("commit")
    assert not git.ran("push")
    assert not any(r.method == "POST" for r in github.requests)


def test_dry_run_describes_the_push_without_making_it():
    result, git, _ = _call({"issue_id": 13, "title": "t", "dry_run": True})
    assert result.ok
    assert "dry_run" in result.data
    assert not git.ran("push")


def test_the_token_never_appears_in_a_push_failure():
    # The remote is HTTPS, so the credential is in the URL git was handed —
    # and git echoes that URL back in its own error message.
    git = FakeGit(
        fail_on="push",
        fail_stderr=f"fatal: could not read from https://x-access-token:{FAKE_TOKEN}@github.com/o/r.git",
    )
    result, _, _ = _call({"issue_id": 13, "title": "t"}, git=git)
    assert not result.ok
    assert FAKE_TOKEN not in result.error_code


def test_the_push_url_carries_the_credential_but_the_receipt_does_not():
    result, git, _ = _call({"issue_id": 13, "title": "t"})
    push = next(c for c in git.calls if "push" in c)
    assert any(FAKE_TOKEN in arg for arg in push), "the push must actually authenticate"
    assert FAKE_TOKEN not in result.data


@pytest.mark.parametrize("failing, expected", [
    ("checkout", "internal: git checkout failed"),
    ("commit", "internal: git commit failed"),
])
def test_a_git_failure_stops_before_the_pr_is_created(failing, expected):
    git = FakeGit(fail_on=failing, fail_stderr="something went wrong")
    result, _, github = _call({"issue_id": 13, "title": "t"}, git=git)
    assert result.error_code.startswith(expected)
    assert not any(r.method == "POST" for r in github.requests)


def test_a_refused_pr_creation_is_returned_with_its_class():
    github = FakeGitHub(create_response=httpx.Response(403, text="Resource not accessible"))
    result, _, _ = _call({"issue_id": 13, "title": "t"}, github=github)
    assert result.error_code == "denied: HTTP 403"


@pytest.mark.parametrize("arguments, expected", [
    ({"title": "t"}, "validation: missing issue_id"),
    ({"issue_id": 13}, "validation: missing title"),
    ({"issue_id": 13, "title": "   "}, "validation: missing title"),
])
def test_bad_arguments_are_rejected_before_touching_git(arguments, expected):
    result, git, github = _call(arguments)
    assert result.error_code == expected
    assert not git.calls
    assert not github.requests


def test_absent_token_is_an_auth_error(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result, git, _ = _call({"issue_id": 13, "title": "t"})
    assert result.error_code == "auth: GITHUB_TOKEN is not set"
    assert not git.calls


def test_it_is_declared_as_a_write_so_the_runtime_gate_sees_it():
    assert open_pr.side_effect is True
