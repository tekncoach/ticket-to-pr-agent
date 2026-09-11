# rag/add_source.py
#
# The "add a document" interface a real ingestion pipeline needs somewhere:
# a place to register a new source and have it stored, without hand-editing
# manifest.json's JSON in an editor. Not a web form — this tool's users are
# engineers operating a knowledge base, not end customers — but one command
# instead of manual JSON surgery, with the PII/license review gate enforced
# by the tool (an unreviewed entry is recorded but not ingested) rather than
# only documented as a convention.
#
# Run it:
#   uv run --env-file .env python -m rag.add_source <path> \
#     --license "..." [--title X] [--layer L] [--reviewed]
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag.ingest import chunk_file, embed_and_upsert

MANIFEST_PATH = Path("data/kb/manifest.json")


def _load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    return json.loads(MANIFEST_PATH.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register (and, once reviewed, ingest) a new corpus source."
    )
    parser.add_argument("path", help="Path to the document (.md or .pdf).")
    parser.add_argument("--title", help="Defaults to the file's stem.")
    parser.add_argument("--layer", default="default")
    parser.add_argument(
        "--license", required=True,
        help="License/redistribution note. Required, not optional — every "
             "existing manifest entry carries one; a source with none isn't "
             "trackable, which is the whole point of the manifest.",
    )
    parser.add_argument(
        "--reviewed", action="store_true",
        help="Confirms you checked this source for PII before ingesting it. "
             "Without it, the entry is recorded but skipped — same gate "
             "rag/build_corpus.py already enforces for every other entry.",
    )
    args = parser.parse_args()

    path = Path(args.path).resolve()
    if not path.exists():
        raise SystemExit(f"no such file: {path}")

    manifest = _load_manifest()
    if any(e.get("path") == str(path) for e in manifest):
        raise SystemExit(f"{path} is already in the manifest — edit data/kb/manifest.json directly instead of adding a duplicate.")

    title = args.title or path.stem
    manifest.append({
        "path": str(path),
        "title": title,
        "layer": args.layer,
        "license": args.license,
        "pii_reviewed": args.reviewed,
    })
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"registered: {title} (pii_reviewed={args.reviewed})")

    if not args.reviewed:
        print("Not ingested. Rerun with --reviewed once you've checked it for PII/license, "
              "or `make ingest` to pick up everything reviewed so far.")
        return

    chunks = chunk_file(path)
    n = embed_and_upsert(chunks, collection=args.layer)
    print(f"ingested {n} chunks")


if __name__ == "__main__":
    main()
