# rag/retrieve.py
#
# Hybrid: BM25 (FTS5, lexical — exact terms, identifiers, rare words) fused
# with dense vector (semantic — paraphrase, synonymy) via Reciprocal Rank
# Fusion. RRF is picked over trying to normalize and add the two raw scores
# because they live on incomparable scales (a cosine-ish similarity vs a
# BM25 log-odds score) — RRF only needs each list's *rank order*, not its
# score magnitude, which is exactly why it's the standard way to combine
# a lexical and a semantic leg without inventing a weighting scheme.
from __future__ import annotations

import os
import re

from huggingface_hub import InferenceClient

from rag.ingest import EMBEDDING_MODEL
from rag.store import get_db, serialize

# How many candidates each leg contributes to the fusion, before it's cut
# down to the caller's k. Wider than k so a chunk that's mediocre-but-present
# on one leg still has a chance if it's strong on the other.
_CANDIDATE_POOL = 30
_RRF_K = 60  # standard RRF constant; not tuned against a real smoke set yet

_FTS5_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _build_filters(filters: dict | None) -> tuple[str, list]:
    where_clauses = []
    params: list = []
    for column, value in (filters or {}).items():
        # Deliberately not an arbitrary column: prevents a caller-supplied
        # filter key from ever reaching raw SQL string interpolation.
        if column not in ("source", "title", "section", "acl", "collection"):
            raise ValueError(f"unknown filter: {column}")
        where_clauses.append(f"chunk_meta.{column} = ?")
        params.append(value)
    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""
    return where_sql, params


def _fts5_query(text: str) -> str:
    # Natural-language questions ("What is...?") aren't valid FTS5 query
    # syntax as-is (bareword AND/OR/NOT, unbalanced quotes). Quoting each
    # token and OR-ing them is the forgiving option: any shared word is a
    # candidate, rather than requiring every word to match (which a real
    # question almost never would).
    tokens = _FTS5_TOKEN_RE.findall(text)
    return " OR ".join(f'"{t}"' for t in tokens)


def _dense_search(db, query_vector, where_sql: str, params: list) -> list[str]:
    rows = db.execute(
        f"""
        SELECT chunk_meta.chunk_id
        FROM vec_chunks
        JOIN chunk_meta ON chunk_meta.rowid = vec_chunks.rowid
        WHERE vec_chunks.embedding MATCH ? AND k = ?{where_sql}
        ORDER BY vec_chunks.distance
        """,
        (serialize(query_vector.tolist()), _CANDIDATE_POOL, *params),
    ).fetchall()
    return [r[0] for r in rows]


def _bm25_search(db, query: str, where_sql: str, params: list) -> list[str]:
    fts_query = _fts5_query(query)
    if not fts_query:
        return []
    rows = db.execute(
        f"""
        SELECT chunk_meta.chunk_id
        FROM fts_chunks
        JOIN chunk_meta ON chunk_meta.rowid = fts_chunks.rowid
        WHERE fts_chunks.text MATCH ?{where_sql}
        ORDER BY bm25(fts_chunks)
        LIMIT ?
        """,
        (fts_query, *params, _CANDIDATE_POOL),
    ).fetchall()
    return [r[0] for r in rows]


def _reciprocal_rank_fusion(*ranked_lists: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
    return scores


def search_kb(query: str, k: int = 6, filters: dict | None = None) -> list[dict]:
    """Return [{id, text, score, source, title, citation}]"""
    client = InferenceClient(token=os.environ.get("HF_TOKEN"))
    query_vector = client.feature_extraction(query, model=EMBEDDING_MODEL, normalize=True)

    where_sql, params = _build_filters(filters)
    db = get_db()
    dense_ids = _dense_search(db, query_vector, where_sql, params)
    bm25_ids = _bm25_search(db, query, where_sql, params)
    fused = _reciprocal_rank_fusion(dense_ids, bm25_ids)
    top_ids = sorted(fused, key=fused.get, reverse=True)[:k]

    if not top_ids:
        db.close()
        return []

    placeholders = ",".join("?" * len(top_ids))
    rows = db.execute(
        f"SELECT chunk_id, text, source, title FROM chunk_meta "
        f"WHERE chunk_id IN ({placeholders})",
        top_ids,
    ).fetchall()
    db.close()
    by_id = {chunk_id: (text, source, title) for chunk_id, text, source, title in rows}

    results = []
    for chunk_id in top_ids:
        text, source, title = by_id[chunk_id]
        results.append({
            "id": chunk_id,
            "text": text,
            # A fused RRF score, not a raw similarity — the two legs live on
            # incomparable scales (see module docstring), so there is no
            # single "distance" left to report once they're combined. The
            # grounding threshold τ (Day 4's INSUFFICIENT_CONTEXT rule) has
            # to be calibrated against *this* number, on the real smoke
            # set — not reused from the dense-only score's old range.
            "score": fused[chunk_id],
            "source": source,
            "title": title,
            "citation": f"[{title}#{chunk_id.split('#', 1)[-1]}]",
        })
    return results


# System prompt fragment
GROUNDING = """
You answer ONLY from tool results. For each factual claim, cite [source#chunk_id].
If retrieval scores are low or sources conflict, respond with:
INSUFFICIENT_CONTEXT: <what is missing>
Never invent ticket IDs, policies, or URLs.
"""
