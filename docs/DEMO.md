# Demo script

Three minutes, four clicks, on the page at `/` (see the live URL in the [README](../README.md#live)). Each click is there to fail differently.

| Click | What should happen |
|---|---|
| **Ask the knowledge base** | `search_kb` runs, the answer carries citations like `[dora-2025-full-report#57.0]` |
| **Ask for a write** | `comment_on_ticket` returns `would comment on …#13 (SHADOW_MODE, nothing posted)`: a receipt, not a write |
| **Ask something off-corpus** | a refusal, grounded in what retrieval actually returned rather than in the model's general knowledge |
| **Break it** | three attempts to reach `crypto.py`, three refusals, then the run stops itself: *"Trying again is not making progress — this is blocked on purpose, so a human has to decide whether the boundary should move."* |

Then click any past run in **Recent runs**. The trace replays: the system prompt it was given, a timeline of every tool call expandable onto its arguments and its result, the typed error class where something failed, and the sentence the agent ended on. A bad answer becomes a session you can open and read.

A recording of a replay is in [`demo/`](demo/): [`ticket-to-pr.gif`](demo/ticket-to-pr.gif) and the full-resolution [`ticket-to-pr.webm`](demo/ticket-to-pr.webm).
