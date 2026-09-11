"""Unit tests for rag/embeddings.py's retry-with-backoff. time.sleep is
mocked so these run instantly regardless of the real backoff delays;
InferenceClient.feature_extraction is mocked so no network call happens.
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rag.embeddings import EmbeddingServiceError, embed

_REQUEST = httpx.Request("POST", "https://router.huggingface.co/hf-inference")


def _http_error():
    return httpx.ConnectError("boom", request=_REQUEST)


def test_succeeds_on_first_try_without_sleeping():
    fake_client = MagicMock()
    fake_client.feature_extraction.return_value = "vectors"
    with patch("rag.embeddings.InferenceClient", return_value=fake_client), \
         patch("rag.embeddings.time.sleep") as mock_sleep:
        result = embed("query", model="some-model")

    assert result == "vectors"
    mock_sleep.assert_not_called()
    fake_client.feature_extraction.assert_called_once()


def test_retries_then_succeeds():
    fake_client = MagicMock()
    fake_client.feature_extraction.side_effect = [_http_error(), _http_error(), "vectors"]
    with patch("rag.embeddings.InferenceClient", return_value=fake_client), \
         patch("rag.embeddings.time.sleep") as mock_sleep:
        result = embed("query", model="some-model")

    assert result == "vectors"
    assert fake_client.feature_extraction.call_count == 3
    assert mock_sleep.call_count == 2  # backoff between attempt 1->2 and 2->3
    # exponential: base_delay * 2**0, base_delay * 2**1
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays[1] > delays[0]


def test_raises_embedding_service_error_after_exhausting_retries():
    fake_client = MagicMock()
    fake_client.feature_extraction.side_effect = _http_error()
    with patch("rag.embeddings.InferenceClient", return_value=fake_client), \
         patch("rag.embeddings.time.sleep"):
        with pytest.raises(EmbeddingServiceError, match="after 3 attempts"):
            embed("query", model="some-model")

    assert fake_client.feature_extraction.call_count == 3
