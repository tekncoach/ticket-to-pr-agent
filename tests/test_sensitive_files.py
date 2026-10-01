"""The agent must not read a credential file, whichever tool it reaches for.

Found by testing it, not by reading: with a .env and a private key in the
checkout, `cat .env`, `cat id_rsa`, `grep -r KEY .` and the editor's view all
returned the secret. It would have gone to the model and into the run trace. The
editor had a denylist of two names configured for the reference target and the
shell had none.

Hermetic: a temporary workspace stands in for the checkout, no model, no network.
"""
from unittest.mock import patch

import pytest

from agent.sensitive_files import sensitive_pattern
from tools.bash import bash
from tools.edit_file import edit_file

SECRET = "API_KEY=sk-live-must-never-be-read"


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / ".env").write_text(SECRET + "\n")
    (tmp_path / ".env.example").write_text("API_KEY=changeme\n")
    (tmp_path / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    (tmp_path / "server.pem").write_text("-----BEGIN CERTIFICATE-----\n")
    (tmp_path / "app.py").write_text("API_KEY = os.environ['API_KEY']\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(SECRET + "\n")
    return tmp_path


def run(workspace, command):
    with patch("tools.bash.WORKSPACE", workspace):
        return bash.handler({"command": command})


# --- the names -------------------------------------------------------------

@pytest.mark.parametrize("name", [".env", ".env.production", ".env.local", "id_rsa", "id_ed25519",
                                  "server.pem", "tls.key", "keystore.p12", ".netrc", ".git-credentials",
                                  "credentials.json", "ID_RSA", "Server.PEM"])
def test_credential_file_names_are_recognised(name):
    assert sensitive_pattern(name) is not None


@pytest.mark.parametrize("name", [".env.example", ".env.sample", ".env.template", ".env.dist",
                                  "app.py", "environment.py", "monkey.py", "README.md", "keyboard.py",
                                  "public_key.md", "id_rsa_notes.md"])
def test_templates_and_ordinary_files_are_not(name):
    # A template is read by everyone and holds no secret; blocking it would make
    # the guard one people switch off, which is how guards die.
    assert sensitive_pattern(name) is None


# --- the shell -------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "cat .env", "cat ./.env", "cat config/.env", "cat id_rsa", "head -1 .env", "tail -n 1 .env",
    "sed -n p .env", "awk 1 .env", "wc -c .env", "cat server.pem", "cat .e*", "cat config/../.env",
])
def test_the_shell_refuses_to_read_a_credential_file(workspace, command):
    result = run(workspace, command)
    assert not result.ok, f"{command!r} returned: {result.data!r}"
    assert result.error_code.startswith("denied:")
    assert "sensitive file" in result.error_code
    assert SECRET not in (result.data or "")


def test_a_recursive_grep_does_not_read_the_credential_files_it_walks_past(workspace):
    result = run(workspace, "grep -rn API_KEY .")
    assert result.ok
    assert SECRET not in result.data, "the recursive search read a .env"
    assert "app.py" in result.data, "and it must still search the files it is allowed to"


@pytest.mark.parametrize("flag", ["-r", "-rn", "-Rn", "-ri", "--recursive"])
def test_every_spelling_of_recursive_grep_is_covered(workspace, flag):
    assert SECRET not in run(workspace, f"grep {flag} API_KEY .").data


def test_a_git_revision_path_is_covered(workspace):
    # `git show HEAD:.env` reads a tracked file without ever naming a path on
    # disk, so it has to be recognised by the part after the colon.
    result = run(workspace, "git show HEAD:.env")
    assert not result.ok and "sensitive file" in result.error_code


def test_the_shell_still_reads_what_it_should(workspace):
    assert run(workspace, "cat app.py").ok
    assert run(workspace, "cat .env.example").ok
    assert run(workspace, "ls -a").ok


def test_a_search_pattern_that_looks_like_a_credential_name_is_not_a_file(workspace):
    # "config.key" is something to search for, not a file in this checkout.
    # Refusing it would break an ordinary grep for no protection.
    assert run(workspace, "grep -n config.key app.py").ok


# --- the editor ------------------------------------------------------------

@pytest.fixture
def authorised():
    from agent.consent import authorise, clear
    from agent.runtime import ToolResult
    authorise(1)
    with patch("tools.edit_file.check_ready", return_value=ToolResult(ok=True, data={"number": 1})):
        yield
    clear()


@pytest.mark.parametrize("command, extra", [
    ("view", {}), ("create", {"file_text": "x"}),
    ("str_replace", {"old_str": "API_KEY", "new_str": "X"}), ("insert", {"insert_line": 1, "new_str": "x"}),
])
def test_the_editor_refuses_every_command_on_a_credential_file(workspace, authorised, command, extra):
    with patch("tools.edit_file.WORKSPACE", workspace):
        result = edit_file.handler({"command": command, "path": ".env", **extra})
    assert not result.ok and result.error_code.startswith("denied:")
    assert SECRET not in (result.data or "")


def test_the_editor_still_reaches_a_template_and_ordinary_source(workspace, authorised):
    with patch("tools.edit_file.WORKSPACE", workspace):
        assert edit_file.handler({"command": "view", "path": ".env.example"}).ok
        assert edit_file.handler({"command": "view", "path": "app.py"}).ok


def test_the_operator_can_add_names_for_a_target(monkeypatch):
    # The list is per target: a repository's secrets are not all called .env.
    monkeypatch.setenv("SENSITIVE_FILES_EXTRA", "vault.token,*.secret")
    import importlib

    import agent.config
    import agent.sensitive_files
    importlib.reload(agent.config)
    importlib.reload(agent.sensitive_files)
    try:
        assert agent.sensitive_files.sensitive_pattern("vault.token") is not None
        assert agent.sensitive_files.sensitive_pattern("db.secret") is not None
        assert agent.sensitive_files.sensitive_pattern(".env") is not None, "extra adds, never replaces"
    finally:
        monkeypatch.delenv("SENSITIVE_FILES_EXTRA")
        importlib.reload(agent.config)
        importlib.reload(agent.sensitive_files)


# --- what the name list does not cover, pinned so it cannot be claimed away ----
#
# The guard refuses credential file NAMES. A secret inside a file that is allowed,
# or in a credential file's history, still gets through. The risk memo says so;
# these two tests are the same sentence, enforced. If either ever goes red because
# the gap closed, the memo has to change in the same commit.

def test_a_secret_inside_an_allowed_file_is_not_caught(workspace):
    (workspace / "settings.py").write_text('AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n')
    result = run(workspace, "cat settings.py")
    assert result.ok
    assert "wJalrXUtnFEMI" in result.data, "this gap is stated in the risk memo; if it closed, say so there"


def test_a_credential_file_still_readable_from_git_history_is_not_caught(workspace):
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(workspace), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True)
    git("init", "-q"); git("add", ".env"); git("commit", "-q", "-m", "oops, committed a secret")
    (workspace / ".env").unlink()          # gone from the tree, still in the history
    result = run(workspace, "git log -p")
    assert result.ok, result.error_code
    assert SECRET in result.data, "history is not covered by a name list; the memo says so"
