# Verbatim starter skeleton from Day 4 (a10x.dev/sprint?track=build#day-4),
# copied as-is. Not wired to anything yet — see docs/ and the Day 4 corpus
# proposal for the design decisions to apply on top of this before it's
# real (chunk on existing headings/video chapters first, then window; the
# `acl` metadata field named in Day 4's own task list is missing from
# `Chunk` below — a gap in the source template itself, not fixed here).

# rag/ingest.py skeleton
from pathlib import Path
from pydantic import BaseModel

class Chunk(BaseModel):
    id: str
    text: str
    source: str
    title: str
    section: str | None = None
    updated_at: str | None = None

def chunk_markdown(path: Path, max_chars: int = 2200, overlap: int = 300) -> list[Chunk]:
    text = path.read_text()
    # split on headings first, then window
    ...

def embed_and_upsert(chunks: list[Chunk], collection: str) -> int:
    # embeddings = client.embed([c.text for c in chunks])
    # store vectors + metadata; return count
    ...
