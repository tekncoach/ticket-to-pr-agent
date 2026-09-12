# rag/ingest.py
#
# Chunking splits on the document's existing headings first, then windows
# any oversized section — never fixed-size chunking as the first pass.
# Structure the author already put in the document is free retrieval
# metadata, and it makes each citation point at something a human can go
# and find. A sibling chunker for video transcripts (splitting on chapters
# from METADATA.md when present, same principle applied to a different
# kind of structure) is a follow-up, not built here.
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from rag.embeddings import embed
from rag.store import EMBEDDING_DIM, get_db, serialize

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+)$", re.MULTILINE)


def _window(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text into <=max_chars windows with a fixed overlap — the
    fallback used once a section (or, for PDFs, a page) doesn't have finer
    structure to split on. Shared between chunk_markdown and chunk_pdf so
    the two formats don't drift onto slightly different windowing math."""
    if len(text) <= max_chars:
        return [text]
    windows = []
    pos = 0
    step = max_chars - overlap
    while pos < len(text):
        windows.append(text[pos:pos + max_chars])
        pos += step
    return windows


class Chunk(BaseModel):
    id: str
    text: str
    source: str
    title: str
    section: str | None = None
    updated_at: str | None = None
    # Part of the chunk metadata set ({source, title, section,
    # updated_at, acl}). "public" until a real ACL model exists (see
    # docs/MCP-SERVER.md's per-user rights design note for the shape that
    # would fill this in for real).
    acl: str = "public"


def chunk_markdown(path: Path, max_chars: int = 2200, overlap: int = 300, title: str | None = None) -> list[Chunk]:
    text = path.read_text()
    title = title or path.stem
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
        windows = _window(section_text, max_chars, overlap)
        for window_idx, window in enumerate(windows):
            # Deterministic, not random: re-ingesting the same file produces
            # the same ids, so embed_and_upsert's INSERT OR REPLACE actually
            # replaces instead of duplicating. Also doubles as a readable
            # citation id ([source#chunk_id] in the GROUNDING prompt) that
            # points a human at roughly where in the document to look —
            # the same reason the chunker splits on headings in the first
            # place.
            chunks.append(Chunk(
                id=f"{title}#{section_idx}.{window_idx}",
                text=window.strip(),
                source=str(path),
                title=title,
                section=section_title,
                updated_at=updated_at,
            ))
    return chunks


def chunk_pdf(path: Path, max_chars: int = 2200, overlap: int = 300, title: str | None = None) -> list[Chunk]:
    """PDF's structural unit is the page, not a markdown heading — pypdf
    gives no font-size/heading detection, so unlike chunk_markdown this
    doesn't try to find finer structure than that. Each page's extracted
    text is windowed like an oversized markdown section would be; a page
    short enough to fit in one window still gets one chunk. "section" is
    set to "page N" (1-indexed, matching what a human opens the PDF to)
    so expand_to_section() groups a PDF exactly the same way it groups a
    multi-window markdown section, with no format-specific case needed
    there.
    """
    from pypdf import PdfReader

    reader = PdfReader(path)
    title = title or path.stem
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    chunks: list[Chunk] = []
    for page_idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for window_idx, window in enumerate(_window(text, max_chars, overlap)):
            chunks.append(Chunk(
                id=f"{title}#{page_idx}.{window_idx}",
                text=window.strip(),
                source=str(path),
                title=title,
                section=f"page {page_idx + 1}",
                updated_at=updated_at,
            ))
    return chunks


def chunk_file(path: Path, max_chars: int = 2200, overlap: int = 300, title: str | None = None) -> list[Chunk]:
    """Dispatch on extension — the one thing rag/build_corpus.py and
    rag/add_source.py should call, so adding a third format later is one
    branch here, not a change at every call site."""
    if path.suffix.lower() == ".pdf":
        return chunk_pdf(path, max_chars, overlap, title=title)
    return chunk_markdown(path, max_chars, overlap, title=title)


def embed_and_upsert(chunks: list[Chunk], collection: str) -> int:
    if not chunks:
        return 0

    # rag.embeddings.embed() already retries transient HTTP failures with
    # backoff; EmbeddingServiceError only reaches here once that's
    # exhausted, so this is a build script failing loudly with what was
    # being ingested, not swallowing a retry-worthy blip.
    vectors = embed([c.text for c in chunks], model=EMBEDDING_MODEL)
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
