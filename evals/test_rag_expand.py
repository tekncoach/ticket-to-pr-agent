"""Unit tests for rag/retrieve.py's section-expansion helpers — the
parent-document/auto-merging pattern: retrieve on one precise chunk, hand
back the whole section it came from so a table or list split across chunk
boundaries isn't half-missing. Hermetic: a real sqlite file (tmp_path), no
embedding call — chunk_meta is populated directly.
"""
from rag.retrieve import _window_idx, expand_to_section
from rag.store import get_db


def test_window_idx_parses_section_and_window():
    assert _window_idx("Doc#3.0") == 0
    assert _window_idx("Doc#3.2") == 2


def _insert(db, chunk_id, text, section):
    db.execute(
        "INSERT INTO chunk_meta (chunk_id, text, source, title, section, collection) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chunk_id, text, "doc.md", "Doc", section, "test"),
    )


def test_expand_to_section_reassembles_in_original_order(tmp_path):
    db = get_db(str(tmp_path / "test.sqlite3"))
    # Inserted out of order on purpose — expand_to_section must sort by
    # window index, not by insertion or chunk_id text order.
    _insert(db, "Doc#1.1", "second", "Intro")
    _insert(db, "Doc#1.0", "first", "Intro")
    _insert(db, "Doc#2.0", "unrelated section", "Other")
    db.commit()

    assert expand_to_section(db, "Doc", "Intro") == "first\n\nsecond"
    db.close()


def test_expand_to_section_handles_no_heading(tmp_path):
    # A document with no markdown headings at all chunks into section=None
    # (see chunk_markdown) — the SQL must match NULL, not skip it.
    db = get_db(str(tmp_path / "test.sqlite3"))
    _insert(db, "Doc#0.0", "only chunk", None)
    db.commit()

    assert expand_to_section(db, "Doc", None) == "only chunk"
    db.close()
