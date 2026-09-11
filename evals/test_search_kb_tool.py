"""Unit tests for the search_kb tool wrapper. rag.retrieve.search_kb (the
underlying function, which calls Hugging Face) is mocked — this project's
own tool-level tests are hermetic, no live embedding call, no key needed.
"""
from unittest.mock import patch

from tools.search_kb import search_kb


def test_missing_query_rejected():
    result = search_kb.handler({})
    assert not result.ok
    assert result.error_code == "missing_query"


def test_successful_search_returns_data():
    fake_results = [{"id": "Doc#0.0", "text": "x", "score": 0.5,
                      "source": "doc.md", "title": "Doc", "citation": "[Doc#0.0]"}]
    with patch("tools.search_kb._search_kb", return_value=fake_results) as mock_search:
        result = search_kb.handler({"query": "what is x?", "k": 3})

    assert result.ok
    # "source" (an absolute local filesystem path in the real corpus) is
    # deliberately stripped before the agent ever sees it — regression
    # test for the live finding that it gave the agent a target to `bash
    # find`/`view` outside the target repo's workspace.
    assert result.data == [{"id": "Doc#0.0", "text": "x", "score": 0.5,
                             "title": "Doc", "citation": "[Doc#0.0]"}]
    assert "source" not in result.data[0]
    mock_search.assert_called_once_with("what is x?", k=3, filters={"acl": "public"})


def test_default_k_is_six_when_not_specified():
    with patch("tools.search_kb._search_kb", return_value=[]) as mock_search:
        search_kb.handler({"query": "anything"})
    mock_search.assert_called_once_with("anything", k=6, filters={"acl": "public"})


def test_invalid_filter_key_reported_specifically():
    with patch("tools.search_kb._search_kb", side_effect=ValueError("unknown filter: nope")):
        result = search_kb.handler({"query": "x", "filters": {"nope": "y"}})

    assert not result.ok
    assert result.error_code == "invalid_filters: unknown filter: nope"


def test_caller_supplied_acl_is_overridden_not_honored():
    # Regression test for a real, code-confirmed finding (a10x coach
    # review, Day 4): the tool's filters used to pass "acl" straight
    # through to the equality filter in rag/retrieve.py's
    # _build_filters(), so a model (or untrusted text it's reasoning
    # over, e.g. a ticket body) could ask for filters={"acl": "internal"}
    # and get it — a privilege-escalation path with no server-side
    # override. Which ACL bucket gets searched must never come from the
    # caller's own request.
    with patch("tools.search_kb._search_kb", return_value=[]) as mock_search:
        search_kb.handler({"query": "x", "filters": {"acl": "internal", "title": "Doc"}})

    called_filters = mock_search.call_args.kwargs["filters"]
    assert called_filters["acl"] == "public"
    assert called_filters["title"] == "Doc"  # other, legitimate filters still pass through


def test_acl_not_exposed_in_the_tool_schema():
    # The schema is a hint to the model, not the actual boundary (the
    # handler enforces it regardless) — but it should not even suggest
    # "acl" as something the caller can choose.
    assert "acl" not in search_kb.input_schema["properties"]["filters"]["properties"]


def test_embedding_service_error_reported_specifically():
    # rag.embeddings.embed() retries transient HTTP failures itself before
    # ever raising — by the time this reaches the tool handler, it's
    # already an EmbeddingServiceError, not a raw httpx exception.
    from rag.embeddings import EmbeddingServiceError

    with patch("tools.search_kb._search_kb", side_effect=EmbeddingServiceError("boom")):
        result = search_kb.handler({"query": "x"})

    assert not result.ok
    assert result.error_code == "embedding_service_unavailable: boom"
