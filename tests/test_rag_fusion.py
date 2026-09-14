"""Unit tests for the hybrid retrieval's pure logic: Reciprocal Rank Fusion
and the FTS5 query sanitization. No embedding call, no database — these
are the two functions in rag/retrieve.py that don't need either.
"""
from rag.retrieve import _fts5_query, _reciprocal_rank_fusion


def test_rrf_favors_a_chunk_ranked_high_on_both_legs():
    dense = ["a", "b", "c"]
    bm25 = ["b", "a", "c"]
    scores = _reciprocal_rank_fusion(dense, bm25)
    # "a" and "b" each lead one list and are #2 on the other — both should
    # outscore "c", which trails on both.
    assert scores["a"] > scores["c"]
    assert scores["b"] > scores["c"]


def test_rrf_a_hit_on_only_one_leg_still_scores():
    dense = ["a", "b"]
    bm25: list[str] = []  # e.g. the query had no matching keywords at all
    scores = _reciprocal_rank_fusion(dense, bm25)
    assert scores["a"] > scores["b"] > 0


def test_rrf_empty_lists_score_nothing():
    assert _reciprocal_rank_fusion([], []) == {}


def test_fts5_query_quotes_each_token():
    assert _fts5_query("Why betterleaks?") == '"Why" OR "betterleaks"'


def test_fts5_query_empty_on_no_tokens():
    # Punctuation-only input has no alphanumeric tokens to search for —
    # search_kb's _bm25_search treats this as "skip the BM25 leg", not a
    # malformed FTS5 query.
    assert _fts5_query("???") == ""
