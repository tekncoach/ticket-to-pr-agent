# rag/embeddings.py
#
# One place to call the embedding service, with retry-with-backoff and a
# specific error type — both rag/ingest.py (batch ingestion) and
# rag/retrieve.py (query time) had their own unguarded
# client.feature_extraction() call; factored here so a fix to retry/error
# handling can't land in one and drift from the other (coach review,
# Day 4: "client.feature_extraction calls in both rag/ingest.py and
# rag/retrieve.py have no error handling").
from __future__ import annotations

import os
import time

import httpx
from huggingface_hub import InferenceClient

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_S = 0.5


class EmbeddingServiceError(RuntimeError):
    """Raised once every retry attempt against the embedding service has failed."""


def embed(texts, model: str, normalize: bool = True):
    """texts: a single string or a list of strings, same shape
    huggingface_hub's own feature_extraction() accepts. Retries transient
    HTTP failures (timeouts, 5xx, rate limits) with exponential backoff
    (0.5s, 1s) before giving up on the third attempt."""
    client = InferenceClient(token=os.environ.get("HF_TOKEN"))
    last_exc: httpx.HTTPError | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return client.feature_extraction(texts, model=model, normalize=normalize)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_BASE_DELAY_S * (2 ** attempt))
    raise EmbeddingServiceError(
        f"embedding service unavailable after {_RETRY_ATTEMPTS} attempts "
        f"({type(last_exc).__name__}): {last_exc}"
    ) from last_exc
