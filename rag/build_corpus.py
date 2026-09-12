# rag/build_corpus.py
#
# Reads data/kb/manifest.json (gitignored, like the rest of data/ — the
# manifest names local paths outside this repo, some pointing at private
# research notes, and doubles as the license/PII tracking table rather
# than duplicating it in a separate document) and ingests every reviewed
# entry.
#
# Run it:  uv run --env-file .env python -m rag.build_corpus
from __future__ import annotations

import json
from pathlib import Path

from rag.ingest import chunk_file, embed_and_upsert

MANIFEST_PATH = Path("data/kb/manifest.json")


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    total = 0
    for entry in manifest:
        path = Path(entry["path"])
        title = entry.get("title", path.stem)
        if not path.exists():
            print(f"SKIP (missing file): {title}")
            continue
        # The one mechanical enforcement of "track license and PII": an
        # entry that was never reviewed never reaches embed_and_upsert,
        # regardless of what else is in the manifest.
        if not entry.get("pii_reviewed"):
            print(f"SKIP (not PII-reviewed): {title}")
            continue
        chunks = chunk_file(path, title=title)
        n = embed_and_upsert(chunks, collection=entry.get("layer", "default"))
        total += n
        print(f"{n:>3} chunks  {title}")
    print(f"--- {total} chunks total ---")


if __name__ == "__main__":
    main()
