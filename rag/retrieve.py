# rag/retrieve.py
import os

from huggingface_hub import InferenceClient

from rag.ingest import EMBEDDING_MODEL
from rag.store import get_db, serialize


def search_kb(query: str, k: int = 6, filters: dict | None = None) -> list[dict]:
    """Return [{id, text, score, source, title, citation}]"""
    client = InferenceClient(token=os.environ.get("HF_TOKEN"))
    query_vector = client.feature_extraction(query, model=EMBEDDING_MODEL, normalize=True)

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

    db = get_db()
    rows = db.execute(
        f"""
        SELECT chunk_meta.chunk_id, chunk_meta.text, chunk_meta.source,
               chunk_meta.title, vec_chunks.distance
        FROM vec_chunks
        JOIN chunk_meta ON chunk_meta.rowid = vec_chunks.rowid
        WHERE vec_chunks.embedding MATCH ? AND k = ?{where_sql}
        ORDER BY vec_chunks.distance
        """,
        (serialize(query_vector.tolist()), k, *params),
    ).fetchall()
    db.close()

    return [
        {
            "id": chunk_id,
            "text": text,
            # sqlite-vec's default distance is L2, over normalize=True
            # vectors — smaller is more similar. Reported as a similarity
            # score instead (higher is better) so callers/the grounding
            # threshold check don't have to know which metric is under the
            # hood; 1 / (1 + distance) keeps it in (0, 1] without needing
            # distance to be bounded.
            "score": 1.0 / (1.0 + distance),
            "source": source,
            "title": title,
            "citation": f"[{title}#{chunk_id.split('#', 1)[-1]}]",
        }
        for chunk_id, text, source, title, distance in rows
    ]


# System prompt fragment
GROUNDING = """
You answer ONLY from tool results. For each factual claim, cite [source#chunk_id].
If retrieval scores are low or sources conflict, respond with:
INSUFFICIENT_CONTEXT: <what is missing>
Never invent ticket IDs, policies, or URLs.
"""
