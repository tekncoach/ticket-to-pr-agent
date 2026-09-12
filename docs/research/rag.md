# RAG — research: expansion patterns, scale, and formats not yet handled

Companion to [`docs/RAG-CONTEXT-EXPANSION.md`](../RAG-CONTEXT-EXPANSION.md) (what's built: parent-document expansion) and `docs/SPEC.md`'s "Code navigation & RAG" section (what's built: hybrid BM25+dense retrieval, heading-first markdown chunking, page-based PDF chunking). Everything below is named, not built.

## Two more context-expansion patterns

**Sentence-window / neighbor expansion.** Fetch the chunk immediately before and after the matched one (rather than the whole section) — useful when a fact spans a chunk boundary but pulling the entire section would be excessive. `chunk_id`'s `<title>#<section_idx>.<window_idx>` already encodes enough to do this (`_window_idx()` already parses it) — implementing it is a query for `window_idx - 1` and `window_idx + 1` within the same `(title, section_idx)`, not a new mechanism.

*Not built because:* `expand_to_section()` already covers the case this would solve (a fact split across a boundary) more completely, at the cost of a larger `section_text`. *Revisit:* if a section is ever large enough (many windows) that pulling the whole thing is wasteful compared to just the neighbors — not the case at this corpus's scale.

**Contextual Retrieval (Anthropic).** Distinct from expansion: instead of adding context *after* retrieval, this improves the *matching* itself — before embedding/indexing, prepend a short LLM-generated sentence to each chunk situating it in the document ("this chunk is from SPEC.md's SLOs section, discussing the north-star metric") so both the dense and BM25 index carry that context, not just the raw chunk text.

*Not built because:* it costs one LLM call per chunk at ingest time (real, ongoing cost, not a one-time build cost) and neither of the two diagnosed retrieval misses (the DORA cross-lingual gap, the SLOs section ranking 24th for its own query) were conclusively shown to be a *missing-context* problem rather than an embedding-model or fusion-weighting one. *Trigger to revisit:* the smoke-set's hit@k measurement shows a pattern of misses this technique specifically targets — a chunk that's individually ambiguous out of context — rather than guessing it would help.

## Vector store at scale

`rag/store.py` uses `sqlite-vec` — a single local file, no server, no infra to stand up or pay for, verified with a real `INSERT` + KNN `MATCH` round-trip before committing to it. This reversed an earlier, untested assumption that pgvector was "the" choice, made before any of this was actually built.

*Revisit:* if the corpus outgrows what one SQLite file handles comfortably, or concurrent write access becomes a real requirement — at that point Qdrant's local mode (`qdrant-client`, `:memory:` or on-disk, still no server) is the next step up before reaching for a hosted Postgres/pgvector instance. *Trigger:* corpus scale or concurrency, not assumed ahead of time.

## Image / multimodal ingestion

Text only, today — `rag/ingest.py` handles markdown (heading-first) and PDF (page-based), both through the same text-embedding model (`BAAI/bge-m3`), which cannot encode an image at all.

Two real, distinct options, neither built:

- **(a) OCR/caption an image into text first**, feed it through the existing pipeline unchanged — cheap, reuses everything, but lossy (a table in a screenshot becomes an approximate description).
- **(b) Real multimodal embeddings** (e.g. Voyage's `voyage-multimodal-3.5`) — a separate vector table at a different dimension and a `search_kb` redesign for cross-modal queries. Availability never checked.

*Trigger:* a concrete source in the corpus that's actually image-only (a diagram, a screenshot with no transcript) where the loss from skipping it is worse than the cost of building either option.

## Other document formats

Text (markdown) and PDF are the only formats `chunk_file()` handles. Not evaluated in depth — named here so the gap is visible, not because each has a settled plan:

| Format | Likely approach | Real cost |
|---|---|---|
| `.docx` (Word) | `python-docx` to extract paragraphs/headings — closer to markdown's heading-first chunking than PDF's page-based fallback, since `.docx` keeps real heading styles. | One new dependency, one new `chunk_docx()`; probably the cheapest of this list. |
| `.pptx` (PowerPoint) | `python-pptx`, one chunk per slide (title + body text), same shape as `chunk_pdf()`'s one-chunk-per-page fallback. Speaker notes, if wanted, are a second field per slide. | Loses all layout/visual meaning — a slide that's mostly a diagram yields a near-empty chunk. |
| `.csv` | Not clearly worth it as prose RAG content — a CSV is structured/tabular, and dense-embedding a row (or even a whole file) discards the thing that makes a CSV useful (querying by column, aggregating). A text-to-SQL or a dedicated structured-data tool answers "how many X" questions this RAG's chunk-and-embed model was never designed for. *Named, not planned* — revisit only if a specific CSV source is actually needed, and even then, reconsider whether `search_kb` is the right tool for it before writing `chunk_csv()`. |
| Images (`.png`/`.jpeg`) and video | Same two options as "Image / multimodal ingestion" above — this is the same fork, not a new one, just restated per concrete file type. |
| Formats not yet imagined | No plan — the honest answer is "we'll name the fork when a real source in this shape actually shows up," the same discipline as every other entry in this file. |
