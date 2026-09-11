# rag/ingest.py
#
# Chunking follows the Day 4 90-second drill's own answer key, verbatim in
# spirit: split on the document's existing headings first, then window any
# oversized section — never fixed-size chunking as the first pass.
# Structure the author already put in the document is free retrieval
# metadata, and it makes each citation point at something a human can go
# and find. A sibling chunker for video transcripts (splitting on chapters
# from METADATA.md when present, same principle applied to a different
# kind of structure) is a follow-up, not built here — see the Day 4 corpus
# proposal for that design note.
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import InferenceClient
from pydantic import BaseModel

from rag.store import EMBEDDING_DIM, get_db, serialize

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)


class Chunk(BaseModel):
    id: str
    text: str
    source: str
    title: str
    section: str | None = None
    updated_at: str | None = None
    # Named in Day 4's own metadata list ({source, title, section,
    # updated_at, acl}) but missing from the starter template's Chunk
    # model — added here since this is the real implementation, not the
    # verbatim skeleton. "public" until a real ACL model exists (see
    # docs/MCP-SERVER.md's per-user rights design note for the shape that
    # would fill this in for real).
    acl: str = "public"


def chunk_markdown(path: Path, max_chars: int = 2200, overlap: int = 300) -> list[Chunk]:
    text = path.read_text()
    title = path.stem
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    headings = list(_HEADING_RE.finditer(text))
    if not headings:
        sections: list[tuple[str | None, str]] = [(None, text)]
    else:
        sections = []
        for i, m in enumerate(headings):
            start = m.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            sections.append((m.group(2).strip(), text[start:end].strip()))

    chunks: list[Chunk] = []
    for section_idx, (section_title, section_text) in enumerate(sections):
        if not section_text:
            continue
        if len(section_text) <= max_chars:
            windows = [section_text]
        else:
            windows = []
            pos = 0
            step = max_chars - overlap
            while pos < len(section_text):
                windows.append(section_text[pos:pos + max_chars])
                pos += step
        for window_idx, window in enumerate(windows):
            # Deterministic, not random: re-ingesting the same file produces
            # the same ids, so embed_and_upsert's INSERT OR REPLACE actually
            # replaces instead of duplicating. Also doubles as a readable
            # citation id ([source#chunk_id] in the GROUNDING prompt) that
            # points a human at roughly where in the document to look —
            # the same reasoning the drill's own answer gives for chunking
            # on headings in the first place.
            chunks.append(Chunk(
                id=f"{title}#{section_idx}.{window_idx}",
                text=window.strip(),
                source=str(path),
                title=title,
                section=section_title,
                updated_at=updated_at,
            ))
    return chunks


def embed_and_upsert(chunks: list[Chunk], collection: str) -> int:
    if not chunks:
        return 0

    client = InferenceClient(token=os.environ.get("HF_TOKEN"))
    vectors = client.feature_extraction(
        [c.text for c in chunks], model=EMBEDDING_MODEL, normalize=True,
    )
    if vectors.shape[-1] != EMBEDDING_DIM:
        raise RuntimeError(
            f"{EMBEDDING_MODEL} returned {vectors.shape[-1]}-dim vectors, "
            f"but rag/store.py's vec0 table is fixed at {EMBEDDING_DIM} — "
            "update EMBEDDING_DIM if the model changed."
        )

    db = get_db()
    count = 0
    for chunk, vector in zip(chunks, vectors):
        cur = db.execute(
            "INSERT OR REPLACE INTO chunk_meta "
            "(chunk_id, text, source, title, section, updated_at, acl, collection) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (chunk.id, chunk.text, chunk.source, chunk.title, chunk.section,
             chunk.updated_at, chunk.acl, collection),
        )
        db.execute(
            "INSERT OR REPLACE INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            (cur.lastrowid, serialize(vector.tolist())),
        )
        # The BM25 leg: same rowid, kept in sync manually alongside the
        # other two inserts above — see rag/store.py's fts_chunks comment.
        db.execute(
            "INSERT OR REPLACE INTO fts_chunks (rowid, text) VALUES (?, ?)",
            (cur.lastrowid, chunk.text),
        )
        count += 1
    db.commit()
    db.close()
    return count
