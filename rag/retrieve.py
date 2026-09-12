# rag/retrieve.py
#
# Hybrid: BM25 (FTS5 — exact terms, identifiers, rare words) fused with
# dense vector (paraphrase, synonymy) via Reciprocal Rank Fusion. RRF rather
# than normalizing and adding the raw scores, which live on incomparable
# scales (cosine-ish similarity vs BM25 log-odds): RRF needs only each
# list's rank order, so no weighting scheme has to be invented.
from __future__ import annotations

import logging
import re

from rag.embeddings import embed
from rag.ingest import EMBEDDING_MODEL
from rag.store import get_db, serialize

# How many candidates each leg contributes to the fusion, before it's cut
# down to the caller's k. Wider than k so a chunk that's mediocre-but-present
# on one leg still has a chance if it's strong on the other.
_CANDIDATE_POOL = 30
_RRF_K = 60  # standard RRF constant; not tuned against a real smoke set yet

_FTS5_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# Retrieval-quality logging: which leg contributed which candidates, and
# whether BM25 or dense found the top hit — enough to debug "why did
# retrieval miss this doc" without re-running the query by hand. Stdlib
# logging, not agent/event_sink.py's run-scoped trace: search_kb() is called
# from the CLI and tests too. Enable at DEBUG on "rag.retrieve".
_logger = logging.getLogger(__name__)


def _log_retrieval_debug(query: str, dense_ids: list[str], bm25_ids: list[str], top_ids: list[str]) -> None:
    if not _logger.isEnabledFor(logging.DEBUG):
        return
    for chunk_id in top_ids:
        dense_rank = dense_ids.index(chunk_id) + 1 if chunk_id in dense_ids else None
        bm25_rank = bm25_ids.index(chunk_id) + 1 if chunk_id in bm25_ids else None
        legs = [name for name, rank in (("dense", dense_rank), ("bm25", bm25_rank)) if rank is not None]
        _logger.debug(
            "retrieval leg breakdown: query=%r chunk_id=%s legs=%s dense_rank=%s bm25_rank=%s",
            query, chunk_id, legs, dense_rank, bm25_rank,
        )


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


def _window_idx(chunk_id: str) -> int:
    # "<title>#<section_idx>.<window_idx>" — the sort key that puts a
    # section's windows back in their original document order, robust to
    # digit count (unlike sorting chunk_id as plain text).
    return int(chunk_id.rsplit("#", 1)[-1].split(".", 1)[1])


def expand_to_section(db, title: str, section: str | None) -> str:
    """Reassemble every chunk that came from the same document section,
    in original order — the parent-document/auto-merging pattern: retrieve
    on a small precise chunk, but hand back the whole section so a table
    or list split across chunk boundaries isn't half-missing."""
    rows = db.execute(
        "SELECT chunk_id, text FROM chunk_meta WHERE title = ? AND section IS ?",
        (title, section),
    ).fetchall()
    rows.sort(key=lambda r: _window_idx(r[0]))
    return "\n\n".join(text for _, text in rows)


def search_kb(query: str, k: int = 6, filters: dict | None = None, expand: bool = False) -> list[dict]:
    """Return [{id, text, score, source, title, citation}] — text is the
    exact matched chunk. With expand=True, also add "section_text": the
    full section it came from (see expand_to_section), for when a single
    chunk cuts off mid-table or mid-list."""
    query_vector = embed(query, model=EMBEDDING_MODEL)

    where_sql, params = _build_filters(filters)
    db = get_db()
    dense_ids = _dense_search(db, query_vector, where_sql, params)
    bm25_ids = _bm25_search(db, query, where_sql, params)
    fused = _reciprocal_rank_fusion(dense_ids, bm25_ids)
    top_ids = sorted(fused, key=fused.get, reverse=True)[:k]
    _log_retrieval_debug(query, dense_ids, bm25_ids, top_ids)

    if not top_ids:
        db.close()
        return []

    placeholders = ",".join("?" * len(top_ids))
    rows = db.execute(
        f"SELECT chunk_id, text, source, title, section FROM chunk_meta "
        f"WHERE chunk_id IN ({placeholders})",
        top_ids,
    ).fetchall()
    by_id = {chunk_id: (text, source, title, section) for chunk_id, text, source, title, section in rows}

    results = []
    for chunk_id in top_ids:
        text, source, title, section = by_id[chunk_id]
        result = {
            "id": chunk_id,
            "text": text,
            # A fused RRF score, not a raw similarity — the two legs live on
            # incomparable scales (see module docstring), so there is no
            # single "distance" left to report once they're combined. The
            # grounding threshold τ (the INSUFFICIENT_CONTEXT rule) has
            # to be calibrated against *this* number, on the real smoke
            # set — not reused from the dense-only score's old range.
            "score": fused[chunk_id],
            "source": source,
            "title": title,
            "citation": f"[{title}#{chunk_id.split('#', 1)[-1]}]",
        }
        if expand:
            result["section_text"] = expand_to_section(db, title, section)
        results.append(result)
    db.close()
    return results


# System prompt fragment
GROUNDING = """
You answer ONLY from tool results. For each factual claim from search_kb, copy
its exact `citation` field into your answer verbatim - never write your own
[source#chunk_id]-shaped text from memory or invent one that looks similar.
If retrieval scores are low, sources conflict, or the retrieved text doesn't
actually support what's being asked, respond with:
INSUFFICIENT_CONTEXT: <what is missing>
Never invent ticket IDs, policies, or URLs.
"""
