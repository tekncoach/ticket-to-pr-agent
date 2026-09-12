"""Retrieval-quality logging: which leg contributed which candidates, and
whether BM25 or dense found the eventual top hit. Hermetic: embed() and both search legs are mocked, a real tmp
sqlite db backs the chunk_meta lookup — no live HF call, no key needed.
"""
import logging
from unittest.mock import patch

from rag.retrieve import search_kb
from rag.store import get_db


def test_retrieval_debug_logging_shows_which_leg_found_each_result(tmp_path, caplog):
    db_path = str(tmp_path / "test.sqlite3")
    db = get_db(db_path)
    db.execute(
        "INSERT INTO chunk_meta (chunk_id, text, source, title, section, collection) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Doc#0.0", "hello world", "doc.md", "Doc", None, "test"),
    )
    db.commit()

    with patch("rag.retrieve.get_db", return_value=db), \
         patch("rag.retrieve.embed", return_value="fake-vector"), \
         patch("rag.retrieve._dense_search", return_value=["Doc#0.0"]), \
         patch("rag.retrieve._bm25_search", return_value=[]), \
         caplog.at_level(logging.DEBUG, logger="rag.retrieve"):
        results = search_kb("hello", k=1)

    assert len(results) == 1
    debug_lines = [r.getMessage() for r in caplog.records]
    assert any("chunk_id=Doc#0.0" in line and "legs=['dense']" in line for line in debug_lines), debug_lines
    assert any("dense_rank=1" in line and "bm25_rank=None" in line for line in debug_lines), debug_lines


def test_no_debug_logging_emitted_below_debug_level(tmp_path, caplog):
    db_path = str(tmp_path / "test.sqlite3")
    db = get_db(db_path)
    db.execute(
        "INSERT INTO chunk_meta (chunk_id, text, source, title, section, collection) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Doc#0.0", "hello world", "doc.md", "Doc", None, "test"),
    )
    db.commit()

    with patch("rag.retrieve.get_db", return_value=db), \
         patch("rag.retrieve.embed", return_value="fake-vector"), \
         patch("rag.retrieve._dense_search", return_value=["Doc#0.0"]), \
         patch("rag.retrieve._bm25_search", return_value=[]), \
         caplog.at_level(logging.INFO, logger="rag.retrieve"):
        search_kb("hello", k=1)

    assert caplog.records == []
