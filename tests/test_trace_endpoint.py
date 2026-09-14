"""Request correlation and the replay endpoint. Hermetic — no API call, no
key; the runtime is patched and traces are written into tmp_path.

The property under test is the one the day's drill names: an id a caller can
paste back and get the exact session out. That only works if the id the header
returns is the id the trace is filed under.
"""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agent.service import _safe_run_id, app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.service.SESSIONS_DIR", tmp_path)
    return TestClient(app), tmp_path


def _write_trace(sessions, run_id, events):
    (sessions / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )


def test_a_response_carries_the_request_id_header(client):
    api, _ = client
    response = api.get("/health")
    assert response.headers["x-request-id"]


def test_a_supplied_request_id_is_echoed_back(client):
    api, _ = client
    response = api.get("/health", headers={"x-request-id": "abc123"})
    assert response.headers["x-request-id"] == "abc123"


def test_the_header_id_becomes_the_run_id(client):
    # The whole point of the binding: the id the caller sees is the name of
    # the thing they can replay. Two ids would make the header decorative.
    api, _ = client
    seen = {}

    class _Runtime:
        def run(self, message, run_id=None):
            seen["run_id"] = run_id
            return {"run_id": run_id, "answer": "hi", "trace": []}

    with patch("agent.service._get_runtime", return_value=_Runtime()), \
         patch("agent.service.llm_ready", return_value=True):
        response = api.post("/v1/chat", json={"message": "hello"},
                            headers={"x-request-id": "deadbeef"})

    assert seen["run_id"] == "deadbeef"
    assert response.json()["run_id"] == "deadbeef"
    assert response.headers["x-request-id"] == "deadbeef"


@pytest.mark.parametrize("supplied", [
    "../../etc/passwd", "not-hex", "abc/def", "a" * 40, "", "  ", "AB12!!",
])
def test_a_hostile_request_id_never_reaches_the_filename(client, supplied):
    # The id becomes a path. Without the filter, "../../etc/passwd" is not an
    # identifier, it is a traversal.
    api, _ = client
    response = api.get("/health", headers={"x-request-id": supplied})
    returned = response.headers["x-request-id"]
    assert returned != supplied
    assert _safe_run_id(returned) == returned, "what we hand back is always safe to file under"


def test_uppercase_hex_is_normalised_rather_than_rejected():
    assert _safe_run_id("ABC123") == "abc123"


def test_replaying_a_run_returns_its_events_and_a_summary(client):
    api, sessions = client
    _write_trace(sessions, "7f3a2c", [
        {"event": "llm_call", "turn": 0, "cost_usd": 0.0012},
        {"event": "tool_call", "turn": 0, "tool": "search_kb"},
        {"event": "tool_result", "turn": 0, "tool": "search_kb", "ok": True, "latency_ms": 412.0},
        {"event": "tool_call", "turn": 1, "tool": "comment_on_ticket"},
        {"event": "tool_result", "turn": 1, "tool": "comment_on_ticket",
         "ok": False, "error_code": "rate_limit: HTTP 429", "error_class": "rate_limit",
         "latency_ms": 8300.0},
        {"event": "llm_call", "turn": 1, "cost_usd": 0.0019},
        {"event": "final", "turn": 1},
    ])

    body = api.get("/v1/trace/7f3a2c").json()

    assert body["run_id"] == "7f3a2c"
    assert len(body["events"]) == 7
    assert body["summary"] == {
        "turns": 2, "tool_calls": 2, "failed_tool_calls": 1,
        "cost_usd": pytest.approx(0.0031), "outcome": "final",
    }


def test_the_replay_carries_what_makes_a_retry_explainable(client):
    # The coach's own next step: "why did it retry 3 times and land on
    # rate_limit" has to be answerable from the logs, not by re-running the
    # failure. That needs the class and the duration on the event.
    api, sessions = client
    _write_trace(sessions, "aa11", [
        {"event": "tool_result", "turn": 0, "tool": "comment_on_ticket", "ok": False,
         "error_code": "rate_limit: HTTP 429 — gave up after 3 cycles",
         "error_class": "rate_limit", "latency_ms": 12400.0},
        {"event": "repeated_tool_failure", "turn": 0},
    ])

    failure = api.get("/v1/trace/aa11").json()["events"][0]
    assert failure["error_class"] == "rate_limit"
    assert failure["latency_ms"] == 12400.0
    assert "3 cycles" in failure["error_code"]


def test_an_unfinished_run_says_so_rather_than_implying_it_finished(client):
    api, sessions = client
    _write_trace(sessions, "bb22", [{"event": "tool_call", "turn": 0, "tool": "bash"}])
    assert api.get("/v1/trace/bb22").json()["summary"]["outcome"] == "incomplete"


def test_a_half_written_last_line_serves_the_rest(client):
    # What a crash mid-write looks like. Serving the readable events beats
    # serving nothing, and the missing final event is itself the finding.
    api, sessions = client
    (sessions / "cc33.jsonl").write_text(
        json.dumps({"event": "tool_call", "turn": 0}) + "\n" + '{"event": "tool_res'
    )
    body = api.get("/v1/trace/cc33").json()
    assert len(body["events"]) == 1
    assert body["summary"]["outcome"] == "incomplete"


def test_an_unknown_run_is_a_404_not_an_empty_trace(client):
    api, _ = client
    response = api.get("/v1/trace/abcdef")
    assert response.status_code == 404
    assert "no trace for run abcdef" in response.json()["error"]


@pytest.mark.parametrize("run_id", ["../../../etc/passwd", "not-hex", "a/b"])
def test_a_malformed_run_id_is_refused_before_any_path_is_built(client, run_id):
    api, _ = client
    response = api.get(f"/v1/trace/{run_id}")
    assert response.status_code in (400, 404)
    if response.status_code == 400:
        assert response.json()["error"] == "malformed run_id"


# --- the runs index ---------------------------------------------------------

def test_recent_runs_are_listed_newest_first(client):
    api, sessions = client
    for name, ts in [("aa11", "2026-09-14T10:00:00"), ("bb22", "2026-09-14T12:00:00")]:
        _write_trace(sessions, name, [{"event": "llm_call", "turn": 0, "ts": ts,
                                       "cost_usd": 0.002}, {"event": "final", "turn": 0}])
    import os, time
    os.utime(sessions / "bb22.jsonl", (time.time(), time.time()))

    runs = api.get("/v1/runs").json()["runs"]
    assert [r["run_id"] for r in runs] == ["bb22", "aa11"]
    assert runs[0]["outcome"] == "final"
    assert runs[0]["cost_usd"] == pytest.approx(0.002)


def test_the_message_log_is_not_listed_as_a_run(client):
    # Every run writes two files. Listing both would double the history and
    # offer an id whose .jsonl is conversation content, not events.
    api, sessions = client
    _write_trace(sessions, "aa11", [{"event": "final", "turn": 0}])
    (sessions / "aa11.messages.jsonl").write_text('{"role": "user"}\n')
    assert [r["run_id"] for r in api.get("/v1/runs").json()["runs"]] == ["aa11"]


def test_an_empty_trace_file_is_skipped_rather_than_listed_blank(client):
    api, sessions = client
    (sessions / "empty.jsonl").write_text("")
    _write_trace(sessions, "aa11", [{"event": "final", "turn": 0}])
    assert [r["run_id"] for r in api.get("/v1/runs").json()["runs"]] == ["aa11"]


def test_a_missing_sessions_directory_is_an_empty_list_not_a_crash(client, tmp_path, monkeypatch):
    api, _ = client
    monkeypatch.setattr("agent.service.SESSIONS_DIR", tmp_path / "never-created")
    assert api.get("/v1/runs").json() == {"runs": []}


@pytest.mark.parametrize("limit, expected", [(0, 1), (1, 1), (500, 3)])
def test_the_limit_is_clamped_to_something_sane(client, limit, expected):
    api, sessions = client
    for name in ("aa11", "bb22", "cc33"):
        _write_trace(sessions, name, [{"event": "final", "turn": 0}])
    assert len(api.get(f"/v1/runs?limit={limit}").json()["runs"]) == expected


def test_the_favicon_is_served_rather_than_404ing(client):
    # A data: URI was tried and silently failed to parse, so the browser fell
    # back to /favicon.ico and kept 404ing in the console — which is what an
    # interviewer sees the moment they open devtools.
    api, _ = client
    response = api.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


# --- what the run actually said ---------------------------------------------

def _write_messages(sessions, run_id, messages):
    (sessions / f"{run_id}.messages.jsonl").write_text(
        "\n".join(json.dumps(m) for m in messages) + "\n"
    )


def test_a_replayed_run_carries_the_question_and_the_answer(client):
    # The events file records what the agent DID. Serving only that made a
    # replayed run show its steps and hide its point.
    api, sessions = client
    _write_trace(sessions, "aa11", [{"event": "final", "turn": 1}])
    _write_messages(sessions, "aa11", [
        {"role": "user", "turn": 0, "content": "What are the commit conventions?"},
        {"role": "assistant", "turn": 0, "content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "name": "search_kb"}]},
        {"role": "user", "turn": 0, "content": [{"type": "tool_result"}]},
        {"role": "assistant", "turn": 1, "content": [
            {"type": "text", "text": "Atomic commits, imperative mood [SPEC#2]."}]},
    ])

    body = api.get("/v1/trace/aa11").json()
    assert body["asked"] == "What are the commit conventions?"
    assert body["answer"] == "Atomic commits, imperative mood [SPEC#2]."


def test_narration_between_tool_calls_is_not_mistaken_for_the_answer(client):
    # Every assistant turn carries text. Taking the last text block regardless
    # of position would return "Let me search." as the answer.
    api, sessions = client
    _write_trace(sessions, "bb22", [{"event": "final", "turn": 1}])
    _write_messages(sessions, "bb22", [
        {"role": "user", "turn": 0, "content": "go"},
        {"role": "assistant", "turn": 0, "content": [
            {"type": "text", "text": "Let me search."},
            {"type": "tool_use", "name": "search_kb"}]},
        {"role": "assistant", "turn": 1, "content": [{"type": "text", "text": "The real answer."}]},
    ])
    assert api.get("/v1/trace/bb22").json()["answer"] == "The real answer."


def test_a_run_that_never_answered_says_so_rather_than_inventing_one(client):
    api, sessions = client
    _write_trace(sessions, "cc33", [{"event": "tool_call", "turn": 0}])
    _write_messages(sessions, "cc33", [
        {"role": "user", "turn": 0, "content": "go"},
        {"role": "assistant", "turn": 0, "content": [
            {"type": "text", "text": "Working."}, {"type": "tool_use", "name": "bash"}]},
    ])
    body = api.get("/v1/trace/cc33").json()
    assert body["asked"] == "go"
    assert body["answer"] is None


def test_a_trace_with_no_message_log_still_replays(client):
    # The events file is written independently; one may exist without the other.
    api, sessions = client
    _write_trace(sessions, "dd44", [{"event": "final", "turn": 0}])
    body = api.get("/v1/trace/dd44").json()
    assert body["asked"] is None and body["answer"] is None
    assert body["summary"]["outcome"] == "final"
