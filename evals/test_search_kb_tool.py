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
    mock_search.assert_called_once_with("what is x?", k=3, filters=None)


def test_default_k_is_six_when_not_specified():
    with patch("tools.search_kb._search_kb", return_value=[]) as mock_search:
        search_kb.handler({"query": "anything"})
    mock_search.assert_called_once_with("anything", k=6, filters=None)


def test_invalid_filter_key_reported_specifically():
    with patch("tools.search_kb._search_kb", side_effect=ValueError("unknown filter: nope")):
        result = search_kb.handler({"query": "x", "filters": {"nope": "y"}})

    assert not result.ok
    assert result.error_code == "invalid_filters: unknown filter: nope"
