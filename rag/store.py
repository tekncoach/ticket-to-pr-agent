# rag/store.py
#
# The vector store: sqlite-vec, a single local file — no server, no
# Postgres/pgvector. Verified live before committing to it (see
# docs/SPEC.md's Deferred architecture decisions): a real INSERT + KNN
# MATCH query round-trip against sqlite-vec 0.1.9, not assumed from its
# README. Qdrant's local mode is the named upgrade path if the corpus
# ever outgrows a single SQLite file (filtering on payload indices,
# hybrid search built in) — not needed at this scale.
from __future__ import annotations

import os
import sqlite3
import struct

import sqlite_vec

# BAAI/bge-small-en-v1.5's output dimension (HF's own recommended default
# for the feature-extraction task) — sqlite-vec's vec0 table needs a fixed
# dimension declared up front, so this is tied to EMBEDDING_MODEL below.
EMBEDDING_DIM = 384


def serialize(vector: list[float]) -> bytes:
    """sqlite-vec's own wire format for a float vector column."""
    return struct.pack(f"{len(vector)}f", *vector)


def get_db(path: str | None = None) -> sqlite3.Connection:
    db_path = path or os.environ.get("VECTOR_DB_PATH", "data/kb/kb.sqlite3")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            embedding float[{EMBEDDING_DIM}]
        )
    """)
    # rowid is shared with vec_chunks by construction (see embed_and_upsert) —
    # that's what makes the JOIN in search_kb work; sqlite-vec has no
    # built-in way to store metadata alongside the vector itself.
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunk_meta (
            rowid INTEGER PRIMARY KEY,
            chunk_id TEXT UNIQUE NOT NULL,
            text TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT,
            updated_at TEXT,
            acl TEXT NOT NULL DEFAULT 'public',
            collection TEXT NOT NULL
        )
    """)
    db.commit()
    return db
