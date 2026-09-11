# RAG context expansion — what's built, what isn't

`search_kb()` matches on small chunks (up to 2200 chars) for retrieval precision. Three known patterns exist for giving the caller more than just the one matched fragment — this doc names all three, what's built, and the trigger to revisit each.

## 1. Parent-document / auto-merging — built

`expand_to_section()` in `rag/retrieve.py` reassembles every chunk sharing the same `(title, section)` back into the full original section, in document order (sorted by the window index encoded in `chunk_id`, not insertion order or chunk_id text order). `search_kb(query, expand=True)` adds a `section_text` field per result with this reassembled text alongside the exact matched `text`.

Cost to build this: zero schema migration — `title`/`section` were already columns on every chunk (Day 4's own metadata list), so this is a pure query over data already there.

**Known imperfection, not fixed:** when a section spans more than one window (a section longer than `max_chars`), `chunk_markdown()`'s 300-char overlap between windows means the reassembled `section_text` repeats that overlap verbatim at the join. Harmless redundancy for an LLM to read, but not clean. *Revisit:* trim the known overlap length when concatenating windows, if it ever shows up in a citation or confuses a grounded answer.

## 2. Sentence-window / neighbor expansion — not built

Fetch the chunk immediately before and after the matched one (rather than the whole section) — useful when a fact spans a chunk boundary but pulling the entire section would be excessive. `chunk_id`'s `<title>#<section_idx>.<window_idx>` already encodes enough to do this (`_window_idx()` already parses it) — implementing it is a query for `window_idx - 1` and `window_idx + 1` within the same `(title, section_idx)`, not a new mechanism.

*Not built because:* `expand_to_section()` already covers the case this would solve (a fact split across a boundary) more completely, at the cost of a larger `section_text`. *Revisit:* if a section is ever large enough (many windows) that pulling the whole thing is wasteful compared to just the neighbors — not the case at this corpus's scale.

## 3. Contextual Retrieval (Anthropic) — not built, different mechanism

Distinct from the two above: instead of expanding *after* retrieval, this improves the *matching* itself — before embedding/indexing, prepend a short LLM-generated sentence to each chunk situating it in the document ("this chunk is from SPEC.md's SLOs section, discussing the north-star metric") so both the dense and BM25 index carry that context, not just the raw chunk text.

*Not built because:* it costs one LLM call per chunk at ingest time (real, ongoing cost, not a one-time build cost) and neither of Day 4's two diagnosed retrieval misses (the DORA cross-lingual gap, the SLOs section ranking 24th for its own query) were conclusively shown to be a *missing-context* problem rather than an embedding-model or fusion-weighting one. *Trigger to revisit:* the smoke-set's hit@k measurement (Day 4's own next step) shows a pattern of misses this technique specifically targets — a chunk that's individually ambiguous out of context — rather than guessing it would help.
