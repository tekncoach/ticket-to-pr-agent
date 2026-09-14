"""Unit tests for the bash tool's security guards.

All hermetic — tmp_path stands in for WORKSPACE, no dependency on a real
target repo checkout. No LLM call, no live service, no key required.

Written to answer one question: which test fails if bash's
allowlist/pipeline guard regresses? This one.
"""
import pytest
from unittest.mock import patch

from agent.errors import ErrorClass, classify, is_retryable
from tools.bash import bash


def _run(tmp_path, command):
    with patch("tools.bash.WORKSPACE", tmp_path):
        return bash.handler({"command": command})


def test_allowed_command_succeeds(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    result = _run(tmp_path, "cat a.txt")
    assert result.ok
    assert result.data == "hello\n"


def test_disallowed_executable_rejected(tmp_path):
    result = _run(tmp_path, "rm -rf a.txt")
    assert not result.ok
    assert result.error_code == "denied: executable not allowed: rm"


def test_curl_rejected(tmp_path):
    result = _run(tmp_path, "curl https://example.com")
    assert not result.ok
    assert result.error_code == "denied: executable not allowed: curl"


def test_shell_operator_rejected(tmp_path):
    result = _run(tmp_path, "cat a.txt && rm -rf /")
    assert not result.ok
    assert result.error_code == "denied: shell operator rejected"


def test_pipe_to_disallowed_binary_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    result = _run(tmp_path, "cat a.txt | rm")
    assert not result.ok
    assert result.error_code == "denied: executable not allowed: rm"


def test_allowed_pipe_still_works(tmp_path):
    (tmp_path / "a.txt").write_text("hello\nworld\n")
    result = _run(tmp_path, "cat a.txt | wc -l")
    assert result.ok
    assert result.data.strip() == "2"


def test_pipe_inside_quoted_pattern_not_split(tmp_path):
    # A "|" inside a quoted grep pattern is regex alternation, not a
    # pipeline boundary — shlex resolves quoting before we ever look for
    # stand-alone "|" tokens.
    (tmp_path / "a.txt").write_text("apple\nbanana\ncherry\n")
    result = _run(tmp_path, 'grep -E "apple|banana" a.txt')
    assert result.ok
    assert "apple" in result.data
    assert "cherry" not in result.data


def test_empty_command_rejected(tmp_path):
    result = _run(tmp_path, "")
    assert not result.ok
    assert result.error_code == "validation: empty command"


def test_too_many_pipeline_stages_rejected(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    result = _run(tmp_path, "cat a.txt | cat a.txt | cat a.txt | cat a.txt")
    assert not result.ok
    assert result.error_code == "validation: more than 3 pipeline stages"


def test_absolute_path_argument_rejected(tmp_path):
    # Regression test: live-observed the agent using an absolute path
    # surfaced in a tool result to `find` a file entirely outside the
    # workspace — cwd alone never stopped this, only an argument-level
    # check does.
    result = _run(tmp_path, "find /etc -name passwd")
    assert not result.ok
    assert result.error_code == "denied: argument escapes workspace: /etc"


def test_path_traversal_argument_rejected(tmp_path):
    result = _run(tmp_path, "cat ../../../etc/passwd")
    assert not result.ok
    assert result.error_code.startswith("denied: argument escapes workspace:")


def test_relative_dot_argument_still_allowed(tmp_path):
    (tmp_path / "x.txt").write_text("x\n")
    result = _run(tmp_path, "find . -name x.txt")
    assert result.ok


def test_flag_and_pattern_arguments_not_mistaken_for_paths(tmp_path):
    # "-la" and "apple|banana" both resolve harmlessly inside the
    # workspace — the guard must not reject arguments just because they
    # aren't obviously filenames.
    (tmp_path / "a.txt").write_text("apple\nbanana\n")
    result = _run(tmp_path, 'grep -E "apple|banana" a.txt')
    assert result.ok


def test_a_refusal_is_classified_denied_and_never_retryable(tmp_path):
    # bash's guards produce refusals, not failures: the taxonomy has to say so,
    # or the retry layer would eventually wear one of them down.
    for command in ("rm -rf /", "grep foo && rm bar", "cat /etc/passwd"):
        result = _run(tmp_path, command)
        assert classify(result.error_code) is ErrorClass.DENIED
        assert not is_retryable(result.error_code)


def test_a_fruitless_search_is_a_result_not_a_failure(tmp_path):
    # grep exiting 1 means "no match", which is an answer. Reporting it as a
    # tool failure cost a real run: two consecutive empty greps tripped the
    # repeated-failure guard and stopped an agent that was working correctly.
    (tmp_path / "a.txt").write_text("hello\n")
    result = _run(tmp_path, "grep nothing-matches-this a.txt")
    assert result.ok, "an empty result is still a result"
    assert "exit 1" in result.data, "the agent is told the search came back empty"


def test_a_refused_command_is_still_a_failure(tmp_path):
    # ok=False stays for the tool failing, not for the command answering no.
    assert not _run(tmp_path, "rm -rf /").ok
    assert not _run(tmp_path, "grep foo && rm bar").ok


def test_git_reads_history_but_never_changes_it(tmp_path):
    # log, diff and blame answer "how does this codebase do things" better
    # than grepping for it. The writing half belongs to open_pr, which owns
    # the branch, the commit and the push.
    assert _run(tmp_path, "git log --oneline -1").error_code != \
        "denied: executable not allowed: git"
    for forbidden in ("git commit -m x", "git push origin main",
                      "git checkout -b feature", "git reset --hard"):
        result = _run(tmp_path, forbidden)
        assert not result.ok
        assert "is not a read subcommand" in result.error_code


def test_an_unvetted_git_subcommand_is_refused_by_default(tmp_path):
    # An allowlist, not a blocklist of the dangerous ones: whatever git adds
    # next is refused until someone looks at it.
    assert "is not a read subcommand" in _run(tmp_path, "git bisect start").error_code


@pytest.mark.parametrize("command", [
    'grep -n hidden a.txt 2>/dev/null',
    'grep -rn merged tests 2>&1',
    'find . -name "*.py" 2> /dev/null',
])
def test_stderr_suppression_is_not_an_operator_worth_refusing(tmp_path, command):
    # Six of the nine commands refused across every real run died on a
    # redirect that cannot write a file and cannot run anything — and this
    # handler already merges stderr into the output, so it changes nothing
    # at all. Stripped before the operator check rather than rejected.
    (tmp_path / "a.txt").write_text("hidden\n")
    (tmp_path / "tests").mkdir(exist_ok=True)
    result = _run(tmp_path, command)
    assert result.ok or "shell operator" not in (result.error_code or "")


def test_a_real_redirect_is_still_refused(tmp_path):
    # Suppressing stderr is not writing a file, and the difference is the
    # whole point of allowing one and not the other.
    assert _run(tmp_path, "grep foo a.txt > out.txt").error_code == \
        "denied: shell operator rejected"
    assert _run(tmp_path, "cat a.txt 2>err.log").error_code == \
        "denied: shell operator rejected"


@pytest.mark.parametrize("command", [
    "git branch -a", "git tag -l", "git remote -v", "git config --list",
])
def test_listing_branches_and_tags_is_reading(tmp_path, command):
    # `git branch -a` was refused in a real run for asking what branches
    # exist. These verbs list when given no name and write when given one.
    result = _run(tmp_path, command)
    assert "not a read subcommand" not in (result.error_code or "")
    assert "names something to change" not in (result.error_code or "")


@pytest.mark.parametrize("command", [
    "git branch feature-x", "git tag v1.0", "git config user.name bob",
    "git remote add origin https://example.com/r.git",
])
def test_naming_something_turns_the_same_verb_into_a_write(tmp_path, command):
    # The subcommand allowlist says which verbs; this says which shape. A
    # positional argument after branch/tag/config is the thing being created.
    assert "names something to change" in _run(tmp_path, command).error_code


def test_cd_into_the_workspace_is_a_no_op_not_a_syntax_error(tmp_path):
    # The prompt hands the agent the workspace's absolute path, so it uses it
    # — and was refused for the operator, which reads as the path being wrong
    # when it was exactly right. Every command already runs with cwd set
    # there, so the cd changes nothing and is stripped.
    (tmp_path / "a.txt").write_text("hello\n")
    result = _run(tmp_path, f"cd {tmp_path} && cat a.txt")
    assert result.ok
    assert "hello" in result.data


def test_cd_into_a_subdirectory_of_the_workspace_is_allowed(tmp_path):
    (tmp_path / "sub").mkdir()
    assert _run(tmp_path, f"cd {tmp_path}/sub && pwd").ok


def test_cd_out_of_the_workspace_is_an_escape_not_an_operator_problem(tmp_path):
    # The error has to name what was actually wrong, or the agent corrects
    # the wrong thing — it would drop the && and try the same escape again.
    result = _run(tmp_path, "cd /etc && cat passwd")
    assert result.error_code == "denied: argument escapes workspace: /etc"


def test_a_bare_cd_is_still_not_an_allowed_executable(tmp_path):
    # Stripping only applies to the `cd X && rest` shape. `cd` alone changes
    # nothing we can observe and is not in the allowlist.
    assert "executable not allowed: cd" in _run(tmp_path, "cd /etc").error_code
