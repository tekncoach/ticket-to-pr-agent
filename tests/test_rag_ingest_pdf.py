"""Unit tests for chunk_pdf's own chunking logic (page grouping, windowing,
deterministic ids) — pypdf.PdfReader is mocked, so this tests our code, not
pypdf's real text extraction (already verified live against two real PDFs
in the corpus; not re-verified here, hermetically, on purpose).
"""
from unittest.mock import MagicMock, patch

from rag.ingest import chunk_pdf


def _fake_page(text: str):
    page = MagicMock()
    page.extract_text.return_value = text
    return page


def _fake_pdf(tmp_path, name="doc.pdf"):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 fake, never actually parsed by pypdf in these tests")
    return path


def test_one_chunk_per_short_page(tmp_path):
    fake_reader = MagicMock()
    fake_reader.pages = [_fake_page("short page 1"), _fake_page("short page 2")]
    path = _fake_pdf(tmp_path)

    with patch("pypdf.PdfReader", return_value=fake_reader):
        chunks = chunk_pdf(path)

    assert len(chunks) == 2
    assert chunks[0].id == "doc#0.0"
    assert chunks[0].section == "page 1"
    assert chunks[1].id == "doc#1.0"
    assert chunks[1].section == "page 2"


def test_blank_pages_skipped(tmp_path):
    fake_reader = MagicMock()
    fake_reader.pages = [_fake_page(""), _fake_page("real content")]
    path = _fake_pdf(tmp_path)

    with patch("pypdf.PdfReader", return_value=fake_reader):
        chunks = chunk_pdf(path)

    assert len(chunks) == 1
    assert chunks[0].section == "page 2"


def test_long_page_windowed_like_an_oversized_markdown_section(tmp_path):
    fake_reader = MagicMock()
    fake_reader.pages = [_fake_page("x" * 5000)]
    path = _fake_pdf(tmp_path)

    with patch("pypdf.PdfReader", return_value=fake_reader):
        chunks = chunk_pdf(path, max_chars=2200, overlap=300)

    assert len(chunks) > 1
    assert all(c.section == "page 1" for c in chunks)
