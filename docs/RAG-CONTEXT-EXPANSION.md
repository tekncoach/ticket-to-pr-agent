# RAG context expansion — what's built

`search_kb()` matches on small chunks (up to 2200 chars) for retrieval precision. This doc covers the one pattern actually built. Two more known patterns are named but not built — see [`docs/research/rag.md`](research/rag.md).

## Parent-document / auto-merging

`expand_to_section()` in `rag/retrieve.py` reassembles every chunk sharing the same `(title, section)` back into the full original section, in document order (sorted by the window index encoded in `chunk_id`, not insertion order or chunk_id text order). `search_kb(query, expand=True)` adds a `section_text` field per result with this reassembled text alongside the exact matched `text`.

Cost to build this: zero schema migration — `title`/`section` were already columns on every chunk, so this is a pure query over data already there.

**Known imperfection, not fixed:** when a section spans more than one window (a section longer than `max_chars`), `chunk_markdown()`'s 300-char overlap between windows means the reassembled `section_text` repeats that overlap verbatim at the join. Harmless redundancy for an LLM to read, but not clean. *Revisit:* trim the known overlap length when concatenating windows, if it ever shows up in a citation or confuses a grounded answer.
