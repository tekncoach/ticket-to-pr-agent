# agent/runtime.py skeleton
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import json, os, time, uuid

import anthropic
import jsonschema

from agent.event_sink import EventSink, JSONLFileSink

# $/MTok, (input, output). Cached prices — verify against
# platform.claude.com/docs before trusting if this file is more than a
# few months old. Unknown models return cost_usd=None rather than a
# guessed number.
MODEL_PRICES_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}

# The `thinking` param has two mutually exclusive shapes, and sending the
# wrong one is a 400: models in this set take {"type": "adaptive"} and
# reject budget_tokens outright; every other model (Haiku 4.5 included —
# our default) needs {"type": "enabled", "budget_tokens": N} explicitly,
# since thinking isn't on by default for it the way it is for these.
ADAPTIVE_THINKING_MODELS = {"claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-fable-5-1"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = MODEL_PRICES_PER_MTOK.get(model)
    if prices is None:
        return None
    in_price, out_price = prices
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error_code: str | None = None

@dataclass
class Tool:
    name: str
    handler: Callable[[dict], ToolResult]
    description: str = ""
    input_schema: dict | None = None  # None for Anthropic-defined tools — see anthropic_type
    side_effect: bool = False
    # Set only for Anthropic-defined client-side tools (e.g. "bash_20250124",
    # "text_editor_20250728"): those are schema-less on the wire — Claude
    # already knows their input shape, we never send input_schema for them.
    # We still write and run the handler ourselves; Anthropic never executes
    # anything server-side for these two.
    anthropic_type: str | None = None

@dataclass
class AgentRuntime:
    model: str
    tools: dict[str, Tool]
    system: str
    max_turns: int = 8
    max_tokens: int = 1024
    allow_side_effects: bool = False
    # Policy guard, not a performance feature: caps how many tool_use blocks
    # in a single turn actually get executed. Calls beyond the cap still get
    # a tool_result (every tool_use needs one), just an error one — Claude's
    # own guidance warns that dropping a tool_result silently trains it to
    # stop using parallel calls at all.
    max_parallel_tool_calls: int = 3
    # Prepared, off by default: flip thinking_enabled to turn it on. The
    # param shape (adaptive vs. budget_tokens) is picked automatically from
    # self.model at call time — see ADAPTIVE_THINKING_MODELS and
    # _thinking_param(). thinking_budget_tokens only matters on the
    # budget_tokens path (Haiku-style models); adaptive models ignore it.
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 2048
    # Where each trace event goes. Default: JSONL file per run under
    # SESSIONS_DIR. Swap for NullSink in tests (no file writes), StdoutSink
    # for live output, or MultiSink(JSONLFileSink(), StdoutSink()) for both —
    # see agent/event_sink.py.
    logger: EventSink = field(default_factory=JSONLFileSink)

    def __post_init__(self) -> None:
        # Built once per AgentRuntime instance, not once per call — the SDK
        # client holds a connection pool, no reason to recreate it per turn.
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

        if self.thinking_enabled and self.model not in ADAPTIVE_THINKING_MODELS:
            # Anthropic's own constraints on this path: budget_tokens >= 1024
            # and strictly less than max_tokens (room must remain for the
            # actual answer after thinking). Fail here, at construction,
            # with a message that says what to change — not as a 400 from
            # the API three turns into a run.
            if self.thinking_budget_tokens < 1024:
                raise RuntimeError("thinking_budget_tokens must be >= 1024.")
            if self.thinking_budget_tokens >= self.max_tokens:
                raise RuntimeError(
                    f"thinking_budget_tokens ({self.thinking_budget_tokens}) must be "
                    f"less than max_tokens ({self.max_tokens}) — raise max_tokens."
                )

    def run(self, user_msg: str) -> dict:
        # Anthropic takes the system prompt as its own messages.create(system=...)
        # kwarg, not as a {"role": "system"} entry in the messages list — that
        # role is invalid there. self.system is passed straight through in _llm.
        messages: list[dict] = [
            {"role": "user", "content": user_msg},
        ]
        trace = []
        run_id = uuid.uuid4().hex[:12]

        # Separate stream from emit()/trace: the full conversation content
        # (what was asked, what the model said or thought, what a tool
        # returned) rather than the structured metrics above. See
        # agent/event_sink.py's EventSink docstring for why these are two
        # files, not one.
        def emit_message(role: str, content: Any, turn: int) -> None:
            self.logger.emit_message(run_id, {
                "run_id": run_id, "ts": _now_iso(), "turn": turn,
                "role": role, "content": content,
            })

        emit_message("user", user_msg, turn=0)

        def emit(event: dict) -> None:
            # Single point of truth: every event is recorded in-memory AND
            # sent to self.logger immediately, never buffered until run()
            # returns. If self._llm() raises (no try/except around it
            # today — a real gap, e.g. a network timeout or 5xx mid-run)
            # the whole process dies right there; buffering until the end
            # would lose every event from a run that had otherwise been
            # working. JSONLFileSink's immediate flush + fsync survives
            # that, and a `kill -9` or power loss too.
            trace.append(event)
            self.logger.emit(run_id, event)

        # Day 3's drill, verbatim: a repeated identical tool call is a spin,
        # not progress. The loop has no memory of its own otherwise — this
        # set is that memory, scoped to this run only. Known future
        # exception, not yet needed: a legitimate polling tool (get_ci_status)
        # would want to call itself again with the same args; not built yet,
        # so not solved yet.
        seen_calls: set[tuple[str, str]] = set()
        for turn in range(self.max_turns):
            t0 = time.time()
            try:
                resp = self._llm(messages, tools=self._anthropic_tools())
            except anthropic.APIError as exc:
                # Covers APIConnectionError (network/timeout), APIStatusError
                # and its subclasses (RateLimitError, InternalServerError —
                # the "network timeout or 5xx" the Day 3 review named) —
                # anything the SDK itself classifies as an API-layer failure.
                # Deliberately NOT a bare `except Exception`: a real bug in
                # our own code (e.g. a KeyError in _anthropic_tools) should
                # still crash loudly, not be absorbed into "the LLM failed."
                # No retry/backoff here — that is Day 5's job by name
                # ("Error handling, retries, and real integration"); this is
                # the minimum so a transient failure is a bounded, reported
                # outcome instead of an uncaught exception with no final event.
                emit({
                    "event": "llm_call_error", "run_id": run_id, "ts": _now_iso(),
                    "turn": turn, "error_type": type(exc).__name__, "error": str(exc),
                })
                return {
                    "run_id": run_id,
                    "error": "llm_call_failed",
                    "answer": (
                        f"Stopping: the model call failed ({type(exc).__name__}). "
                        "No retry attempted here — that is Day 5's job."
                    ),
                    "trace": trace,
                }
            usage = resp.usage
            emit({
                "event": "llm_call", "run_id": run_id, "ts": _now_iso(), "turn": turn,
                "latency_ms": (time.time() - t0) * 1000,
                "message_id": resp.id,
                "model": self.model,             # what we requested (may be an alias)
                "model_resolved": resp.model,    # the actual pinned snapshot Anthropic used
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                # Included WITHIN output_tokens, not additive — a breakdown for
                # observability, not a separate cost line. Always None today:
                # we never request thinking (Haiku 4.5 needs it enabled
                # explicitly, unlike newer models where it's the default).
                "thinking_tokens": (usage.output_tokens_details.thinking_tokens
                                    if usage.output_tokens_details else None),
                # Always 0 today — no cache_control breakpoints anywhere yet,
                # despite the system prompt + tool schemas being identical
                # every turn of a run: a real, unexploited caching win.
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
                "service_tier": usage.service_tier,
                "cost_usd": _cost_usd(self.model, usage.input_tokens, usage.output_tokens),
                "stop_reason": resp.stop_reason,
                # Only ever non-null when stop_reason == "refusal" — without
                # logging it, a refusal would pass through as an unremarkable
                # final answer with no record of why.
                "stop_details": resp.stop_details.model_dump() if resp.stop_details else None,
            })

            # Echo the assistant's own turn back into the history verbatim —
            # without this, messages never grows and the model has amnesia
            # every turn. resp.content is already the right shape (a list of
            # block objects); the SDK accepts it straight back on the next call.
            messages.append({"role": "assistant", "content": resp.content})
            # resp.content is a list of SDK pydantic block objects (TextBlock,
            # ToolUseBlock, and — when thinking_enabled — ThinkingBlock,
            # which is where the model's reasoning actually lives, not just
            # its final text). model_dump() is what makes any of that
            # JSON-serializable for the messages.jsonl file.
            emit_message("assistant", [b.model_dump() for b in resp.content], turn=turn)

            if resp.stop_reason != "tool_use":
                # No tool call this turn: whatever text came back is the answer.
                final_text = "".join(
                    block.text for block in resp.content if block.type == "text"
                )
                emit({"event": "final", "run_id": run_id, "ts": _now_iso(), "turn": turn})
                return {"run_id": run_id, "answer": final_text, "trace": trace}

            # stop_reason == "tool_use": one turn can ask for several tools at
            # once. Every tool_use block needs exactly one tool_result block
            # back, and ALL of them travel together in a single user message —
            # not one message per result.
            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            tool_results = []
            for i, block in enumerate(tool_use_blocks):
                emit({
                    "event": "tool_call", "run_id": run_id, "ts": _now_iso(), "turn": turn,
                    "tool": block.name, "args": block.input,
                })

                signature = (block.name, json.dumps(block.input, sort_keys=True))
                if signature in seen_calls:
                    # Hard stop, not another error tool_result: an error result
                    # gives the model a chance to try again, which is exactly
                    # the spin we're stopping — it already got this identical
                    # call's outcome once, sending it back changes nothing.
                    emit({
                        "event": "duplicate_call_stop", "run_id": run_id, "ts": _now_iso(),
                        "turn": turn, "tool": block.name,
                    })
                    return {
                        "run_id": run_id,
                        "error": "duplicate_tool_call",
                        "answer": (
                            f"Stopping: repeated an identical call to {block.name} "
                            "with the same arguments. Trying again would not "
                            "produce new information."
                        ),
                        "trace": trace,
                    }
                seen_calls.add(signature)

                if i >= self.max_parallel_tool_calls:
                    # Still executed sequentially today (see docs/SDLC-schema.md
                    # for why we haven't parallelized read-only calls yet) — this
                    # cap exists so a single turn can't trigger an unbounded
                    # number of side effects/subprocess spawns/API calls, not to
                    # manage concurrency that doesn't exist yet.
                    result = ToolResult(ok=False, error_code="too_many_parallel_calls")
                else:
                    tool = self.tools.get(block.name)  # .get(), not [block.name]:
                    if tool is None:                   # a hallucinated tool name
                        result = ToolResult(ok=False, error_code="unknown_tool")
                    elif tool.side_effect and not self.allow_side_effects:
                        result = ToolResult(ok=False, error_code="side_effect_not_allowed")
                    elif (schema_error := self._validate_args(tool, block.input)) is not None:
                        result = ToolResult(ok=False, error_code=f"invalid_args: {schema_error}")
                    else:
                        try:
                            result = tool.handler(block.input)
                        except Exception as exc:  # a broken handler must not crash the run
                            result = ToolResult(ok=False, error_code=f"handler_error: {exc}")

                emit({
                    "event": "tool_result", "run_id": run_id, "ts": _now_iso(), "turn": turn,
                    "tool": block.name, "ok": result.ok, "error_code": result.error_code,
                })

                if not result.ok:
                    content = result.error_code or "error"
                elif isinstance(result.data, str):
                    content = result.data  # already text — don't double-encode it
                else:
                    content = json.dumps(result.data)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": not result.ok,
                })

            messages.append({"role": "user", "content": tool_results})
            emit_message("user", tool_results, turn=turn)

        return {"run_id": run_id, "error": "max_turns", "trace": trace}

    @staticmethod
    def _validate_args(tool: Tool, args: dict) -> str | None:
        # Only our own custom tools declare input_schema — Anthropic-defined
        # tools (anthropic_type set) are schema-less on the wire, so there is
        # no schema of ours to check them against; their handlers already do
        # their own minimal checks (missing_path, empty_command, ...).
        if tool.input_schema is None:
            return None
        try:
            jsonschema.validate(instance=args, schema=tool.input_schema)
        except jsonschema.ValidationError as exc:
            return exc.message
        return None

    def _thinking_param(self) -> dict | None:
        if not self.thinking_enabled:
            return None
        if self.model in ADAPTIVE_THINKING_MODELS:
            return {"type": "adaptive"}
        return {"type": "enabled", "budget_tokens": self.thinking_budget_tokens}

    def _llm(self, messages: list[dict], tools: list[dict]) -> anthropic.types.Message:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            messages=messages,
            tools=tools,
        )
        thinking = self._thinking_param()
        if thinking is not None:
            kwargs["thinking"] = thinking
        return self._client.messages.create(**kwargs)

    def _anthropic_tools(self) -> list[dict]:
        # Anthropic-defined client-side tools (bash, text_editor, memory) are
        # declared by type+name only — passing input_schema for one of these
        # is rejected. Everything else is our own custom tool: flat
        # name/description/input_schema, no "type": "function" wrapper.
        schemas = []
        for t in self.tools.values():
            if t.anthropic_type:
                schemas.append({"type": t.anthropic_type, "name": t.name})
            else:
                schemas.append({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                })
        return schemas
