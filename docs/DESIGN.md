# Design decisions

What this project does differently from a chat loop wrapped around an LLM call, and where each decision can be checked: the code, a test, or another doc.

## No agent framework

The tool-calling loop is built directly on `anthropic.messages.create`, with no LangChain or LangGraph. Every retry, stop condition and failure path is in `agent/runtime.py`.

## Native tools where they fit, hand-rolled where it matters

- File exploration and edits use Anthropic's client-side `bash_20250124` and `text_editor_20250728` tools. They are schema-less and hardened at the boundary: an executable allowlist, never `shell=True`, path confinement to the target checkout, and a path denylist for sensitive files.
- GitHub calls are hand-written REST, to keep the mechanics visible.
- `GITHUB_TOKEN` is scoped to the `Authorization` header only. [`tests/test_no_secrets_in_logs.py`](../tests/test_no_secrets_in_logs.py) mocks a real fetch and asserts it never reaches the tool output, and so neither of the two JSONL logs.

## Policy guards the model cannot opt out of

- A hard cap on parallel tool calls.
- JSON-Schema-validated arguments on every custom tool.
- A mode flag (`SHADOW_MODE`) that disables every write tool at once.
- A hard stop the moment the model repeats an identical tool call, so a possible infinite loop becomes a bounded, explainable failure.

## One trace stream per run

One append-only JSONL file per run, flushed and fsynced per event: a crash keeps what already happened, and the demo page can read a trace while it is still being written. Field names follow [OpenTelemetry's GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai) (`gen_ai.tool.call.arguments`, `gen_ai.usage.input_tokens`, `gen_ai.system_instructions`), so exporting to Langfuse, Phoenix or LangSmith is a rename. The conversation lives in the same stream, which is what lets a replay show what the agent said and not only what it did.

## Evals

[`evals/golden.jsonl`](../evals/golden.jsonl) holds the labelled cases: factual QA, tool selection, workflows, refusal, adversarial injection, write consent. Scoring is deterministic where a trace can settle it and explicitly *unchecked* where it cannot, so a clean report never means nobody looked.

The faithfulness judge is calibrated against human labels before anything it says is quoted, and it is still not trusted with the three behaviours it was built for: its residual errors all lean the same way, toward passing invented content. Details in [`evals/JUDGE-CALIBRATION.md`](../evals/JUDGE-CALIBRATION.md).

## Cold audit

[`COLD-AUDIT.md`](COLD-AUDIT.md) is a brief for a reviewer with none of this repository's context, built from seven defect classes this code has actually shipped. One pass found ten defects, seven in code written that week and two exploitable, including a write gate that skipped its own check whenever no ticket had been authorised. Every finding is proved with a command or dropped, and run against the code before it is fixed: one of the ten was a real mechanism with the wrong conclusion, and is recorded as accepted rather than changed.

## Spec

[`SPEC.md`](SPEC.md) states the problem, the tools, the SLOs, and each architecture decision with its trigger to revisit, including the ones later commits reversed.

## Tenancy

Single-tenant automation: one running instance, one `TARGET_REPO`, one service-account `GITHUB_TOKEN`. There is no per-user identity and no isolation between targets beyond running separate instances with separate config, because there is nothing to isolate yet. This is the same reasoning [`SPEC.md`](SPEC.md#users--surfaces) gives for its auth model.

`search_kb`'s `acl` field ([`tools/search_kb.py`](../tools/search_kb.py)) is the one access-control mechanism that exists today, and the server enforces it regardless of what a caller requests. Per-user rights gating is a named, not-yet-built fork: [`research/mcp-server.md`](research/mcp-server.md).
