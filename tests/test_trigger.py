"""The trigger: which issues may be worked, and what the agent is told.

Hermetic — GitHub answers through httpx.MockTransport and the runtime is
patched, so no network, no key, no model call.

The property that matters: the agent:ready label is a contract checked before
the model sees anything, not a suggestion the agent could reason past.
"""
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.tickets import READY_LABEL, check_ready, list_issues, task_prompt
from agent.service import app
from tools.http_client import ResilientClient

FAKE_TOKEN = "github_pat_TOTALLY_FAKE_TEST_TOKEN_never_real"


def _issue(number=13, labels=(READY_LABEL,), title="Add the share link", **extra):
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/o/r/issues/{number}",
        "labels": [{"name": name} for name in labels],
        **extra,
    }


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)


def _github(response):
    def build(tok):
        return ResilientClient(
            "https://api.github.com", tok,
            transport=httpx.MockTransport(lambda request: response),
        )
    return build


def _with_github(response):
    return patch("agent.tickets._build_client", _github(response))


def test_the_queue_shows_the_whole_backlog_and_marks_what_may_be_worked():
    # Not filtered to the allowed rows: a queue that hides the unlabelled
    # issues hides the contract. Marking them shows it, and clicking one is
    # how you watch check_ready refuse.
    listing = [_issue(13), _issue(14, labels=("bug",))]
    with _with_github(httpx.Response(200, json=listing)):
        result = list_issues()
    assert result.ok
    assert [(i["number"], i["ready"]) for i in result.data] == [(13, True), (14, False)]
    assert result.data[0]["title"] == "Add the share link"


def test_the_queue_can_still_be_narrowed_to_the_allowed_rows():
    with _with_github(httpx.Response(200, json=[_issue(13)])) as _:
        result = list_issues(ready_only=True)
    assert result.ok and result.data[0]["ready"] is True


def test_the_queue_filters_out_pull_requests():
    # GitHub's issues endpoint returns pull requests too. A PR is not a ticket,
    # and handing the agent its own output to work would be a loop.
    listing = [_issue(13), _issue(99, pull_request={"url": "..."})]
    with _with_github(httpx.Response(200, json=listing)):
        result = list_issues()
    assert [i["number"] for i in result.data] == [13]


def test_a_secret_pasted_into_a_title_is_redacted_before_the_queue_renders_it():
    # The queue is rendered in a browser, and an issue title is written by
    # anyone.
    leaky = _issue(13, title=f"crash with sk-ant-{'x' * 40} in the config")
    with _with_github(httpx.Response(200, json=[leaky])):
        result = list_issues()
    assert "sk-ant-" not in result.data[0]["title"]


def test_an_unlabelled_issue_is_refused():
    # SPEC.md: "That label is the contract — no label, no run." Stated there
    # since Day 2 and enforced nowhere until this check.
    with _with_github(httpx.Response(200, json=_issue(13, labels=("bug",)))):
        result = check_ready(13)
    assert not result.ok
    assert result.error_code.startswith(f"denied: issue #13 does not carry {READY_LABEL}")
    assert "a human labels an issue" in result.error_code


def test_a_labelled_issue_is_allowed():
    with _with_github(httpx.Response(200, json=_issue(13))):
        result = check_ready(13)
    assert result.ok
    assert result.data["number"] == 13


def test_a_missing_issue_is_not_found_rather_than_denied():
    # Different answers: "you may not" and "there is nothing there".
    with _with_github(httpx.Response(404, json={"message": "Not Found"})):
        result = check_ready(999)
    assert result.error_code == "not_found: HTTP 404"


def test_no_token_refuses_before_any_request():
    import os
    with patch.dict(os.environ, {}, clear=True):
        assert check_ready(13).error_code == "auth: GITHUB_TOKEN is not set"
        assert list_issues().error_code == "auth: GITHUB_TOKEN is not set"


def test_the_task_prompt_orders_the_loop_the_spec_names():
    prompt = task_prompt(13)
    steps = ["fetch_ticket", "search_kb", "bash", "str_replace_based_edit_tool",
             "run_tests", "open_pr"]
    positions = [prompt.index(step) for step in steps]
    assert positions == sorted(positions), "the prompt walks the loop in order"
    assert "#13" in prompt


def test_the_task_prompt_forbids_a_pr_over_a_red_suite():
    # The difference between an agent that reports failure and one that opens
    # a pull request nobody asked for.
    prompt = task_prompt(13)
    assert "do NOT open a pull request" in prompt
    assert "comment_on_ticket" in prompt


# --- the HTTP surface -------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def test_running_an_unlabelled_issue_is_a_403_and_never_reaches_the_model(client):
    ran = []

    class _Runtime:
        def run(self, message, run_id=None):
            ran.append(message)
            return {}

    with _with_github(httpx.Response(200, json=_issue(13, labels=("bug",)))), \
         patch("agent.service.llm_ready", return_value=True), \
         patch("agent.service._get_runtime", return_value=_Runtime()):
        response = client.post("/v1/run", json={"issue": 13})

    assert response.status_code == 403
    assert READY_LABEL in response.json()["error"]
    assert not ran, "the label is checked before the model sees anything"


def test_running_a_labelled_issue_starts_a_run_under_the_request_id(client):
    seen = {}

    class _Runtime:
        def run(self, message, run_id=None):
            seen["prompt"], seen["run_id"] = message, run_id
            return {"run_id": run_id, "answer": "done", "trace": []}

    with _with_github(httpx.Response(200, json=_issue(13))), \
         patch("agent.service.llm_ready", return_value=True), \
         patch("agent.service._get_runtime", return_value=_Runtime()):
        response = client.post("/v1/run", json={"issue": 13},
                               headers={"x-request-id": "beef0001"})

    assert response.status_code == 200
    assert seen["run_id"] == "beef0001"
    assert "#13" in seen["prompt"]
    assert response.json()["issue"]["number"] == 13


def test_running_without_a_key_is_a_503_before_github_is_called(client):
    with patch("agent.service.llm_ready", return_value=False):
        response = client.post("/v1/run", json={"issue": 13})
    assert response.status_code == 503


@pytest.mark.parametrize("payload", [{"issue": 0}, {"issue": -1}, {}, {"issue": "thirteen"}])
def test_a_malformed_issue_number_is_rejected_by_the_schema(client, payload):
    assert client.post("/v1/run", json=payload).status_code == 422


def test_the_queue_endpoint_names_the_label_it_filtered_on(client):
    with _with_github(httpx.Response(200, json=[_issue(13)])):
        body = client.get("/v1/issues").json()
    assert body["label"] == READY_LABEL
    assert body["issues"][0]["number"] == 13


def test_a_github_outage_on_the_queue_is_a_502_not_an_empty_queue(client):
    # An empty list would read as "no work to do", which is a different and
    # much more misleading answer than "I could not ask".
    with _with_github(httpx.Response(500)), patch("tools.http_client.time.sleep"):
        response = client.get("/v1/issues")
    assert response.status_code == 502
    assert "unavailable" in response.json()["error"]
