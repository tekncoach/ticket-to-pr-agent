# agent/runtime.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
import json, os, time, uuid

import anthropic
import jsonschema

from agent.errors import ErrorClass, ToolError
from agent.event_sink import EventSink, JSONLFileSink

# $/MTok, (input, output). Cached prices — re-check against
# platform.claude.com/docs. Unknown models return cost_usd=None, never a guess.
MODEL_PRICES_PER_MTOK = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}

# Two mutually exclusive shapes, and the wrong one is a 400: these models
# take {"type": "adaptive"} and reject budget_tokens; every other model
# (Haiku 4.5, our default) needs {"type": "enabled", "budget_tokens": N}.
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
    # Set only for Anthropic-defined client-side tools ("bash_20250124",
    # "text_editor_20250728"): schema-less on the wire, so we never send
    # input_schema. We still run the handler; Anthropic executes nothing.
    anthropic_type: str | None = None

@dataclass
class AgentRuntime:
    model: str
    tools: dict[str, Tool]
    system: str
    max_turns: int = 8
    max_tokens: int = 1024
    allow_side_effects: bool = False
    # Policy guard, not performance: caps executed tool_use blocks per turn.
    # Calls past the cap still get a tool_result, just an error one —
    # dropping one trains Claude to stop using parallel calls at all.
    max_parallel_tool_calls: int = 3
    # Off by default. The param shape is picked from self.model at call time
    # (see _thinking_param); the budget only applies on the non-adaptive path.
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 2048
    # Where each trace event goes; a JSONL file per run under SESSIONS_DIR.
    # Swap for NullSink / StdoutSink / MultiSink — see agent/event_sink.py.
    logger: EventSink = field(default_factory=JSONLFileSink)

    def __post_init__(self) -> None:
        # Built once per instance: the SDK client holds a connection pool.
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

        if self.thinking_enabled and self.model not in ADAPTIVE_THINKING_MODELS:
            # Anthropic's constraints here: budget >= 1024 and strictly below
            # max_tokens (room must remain for the answer). Fail at
            # construction, not as a 400 three turns into a run.
            if self.thinking_budget_tokens < 1024:
                raise RuntimeError("thinking_budget_tokens must be >= 1024.")
            if self.thinking_budget_tokens >= self.max_tokens:
                raise RuntimeError(
                    f"thinking_budget_tokens ({self.thinking_budget_tokens}) must be "
                    f"less than max_tokens ({self.max_tokens}) — raise max_tokens."
                )

    def run(self, user_msg: str) -> dict:
        # The system prompt goes to messages.create(system=...), not into the
        # messages list — that role is invalid there. Passed through in _llm.
        messages: list[dict] = [
            {"role": "user", "content": user_msg},
        ]
        trace = []
        run_id = uuid.uuid4().hex[:12]

        # A separate stream from emit()/trace: conversation content rather
        # than structured metrics. Why two files: agent/event_sink.py.
        def emit_message(role: str, content: Any, turn: int) -> None:
            self.logger.emit_message(run_id, {
                "run_id": run_id, "ts": _now_iso(), "turn": turn,
                "role": role, "content": content,
            })

        emit_message("user", user_msg, turn=0)

        def emit(event: dict) -> None:
            # Every event is recorded in-memory AND flushed to self.logger
            # immediately, never buffered until run() returns —
            # JSONLFileSink's flush + fsync survives a crash mid-run, a
            # `kill -9`, or power loss.
            trace.append(event)
            self.logger.emit(run_id, event)

        # A repeated identical tool call is a spin, not progress; this set is
        # the loop's only memory of that, scoped to this run. A legitimate
        # polling tool (get_ci_status) would need an exception — not built.
        seen_calls: set[tuple[str, str]] = set()
        for turn in range(self.max_turns):
            t0 = time.time()
            try:
                resp = self._llm(messages, tools=self._anthropic_tools())
            except anthropic.APIError as exc:
                # Anything the SDK classifies as an API-layer failure
                # (network, timeout, 429, 5xx). Deliberately not a bare
                # `except Exception`: a bug of ours must still crash loudly,
                # not be laundered into "the LLM failed". No retry/backoff
                # yet — this is the minimum for a bounded, reported outcome.
                emit({
                    "event": "llm_call_error", "run_id": run_id, "ts": _now_iso(),
                    "turn": turn, "error_type": type(exc).__name__, "error": str(exc),
                })
                return {
                    "run_id": run_id,
                    "error": "llm_call_failed",
                    "answer": (
                        f"Stopping: the model call failed ({type(exc).__name__}). "
                        "No retry was attempted."
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
                # Within output_tokens, not additive — a breakdown, not a cost
                # line. Always None today: we never request thinking.
                "thinking_tokens": (usage.output_tokens_details.thinking_tokens
                                    if usage.output_tokens_details else None),
                # Always 0 today — no cache_control breakpoints yet, despite
                # the prompt + tool schemas repeating every turn: a real,
                # unexploited caching win.
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
                "service_tier": usage.service_tier,
                "cost_usd": _cost_usd(self.model, usage.input_tokens, usage.output_tokens),
                "stop_reason": resp.stop_reason,
                # Non-null only when stop_reason == "refusal" — unlogged, a
                # refusal reads as an unremarkable final answer.
                "stop_details": resp.stop_details.model_dump() if resp.stop_details else None,
            })

            # Echo the assistant's turn back verbatim, or messages never grows
            # and the model has amnesia. resp.content is already the right
            # shape; the SDK accepts it straight back on the next call.
            messages.append({"role": "assistant", "content": resp.content})
            # SDK pydantic blocks (Text, ToolUse, and ThinkingBlock when
            # enabled — where the reasoning lives, not just the final text).
            # model_dump() is what makes them JSON-serializable.
            emit_message("assistant", [b.model_dump() for b in resp.content], turn=turn)

            if resp.stop_reason != "tool_use":
                # No tool call this turn: whatever text came back is the answer.
                final_text = "".join(
                    block.text for block in resp.content if block.type == "text"
                )
                emit({"event": "final", "run_id": run_id, "ts": _now_iso(), "turn": turn})
                return {"run_id": run_id, "answer": final_text, "trace": trace}

            # One turn can ask for several tools. Every tool_use block needs
            # exactly one tool_result back, and they all travel together in a
            # single user message — not one message per result.
            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            tool_results = []
            for i, block in enumerate(tool_use_blocks):
                emit({
                    "event": "tool_call", "run_id": run_id, "ts": _now_iso(), "turn": turn,
                    "tool": block.name, "args": block.input,
                })

                signature = (block.name, json.dumps(block.input, sort_keys=True))
                if signature in seen_calls:
                    # Hard stop, not another error tool_result: an error
                    # invites a retry, which is the spin we're stopping — the
                    # model already has this identical call's outcome.
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
                    # Executed sequentially today (docs/SDLC-schema.md says
                    # why): the cap bounds side effects per turn, it does not
                    # manage concurrency that doesn't exist yet.
                    result = ToolResult(ok=False, error_code=str(ToolError(
                        ErrorClass.DENIED,
                        f"more than {self.max_parallel_tool_calls} tool calls in one turn")))
                else:
                    tool = self.tools.get(block.name)  # .get(), not [block.name]:
                    if tool is None:                   # a hallucinated tool name
                        result = ToolResult(ok=False, error_code=str(
                            ToolError(ErrorClass.VALIDATION, f"unknown tool: {block.name}")))
                    elif tool.side_effect and not self.allow_side_effects:
                        result = ToolResult(ok=False, error_code=str(ToolError(
                            ErrorClass.DENIED, "side effects are not allowed in this run")))
                    elif (schema_error := self._validate_args(tool, block.input)) is not None:
                        result = ToolResult(ok=False, error_code=str(
                            ToolError(ErrorClass.VALIDATION, schema_error)))
                    else:
                        try:
                            result = tool.handler(block.input)
                        except Exception as exc:  # a broken handler must not crash the run
                            result = ToolResult(ok=False, error_code=str(
                                ToolError(ErrorClass.INTERNAL, f"{type(exc).__name__}: {exc}")))

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
        # Only our own tools declare input_schema — Anthropic-defined ones are
        # schema-less on the wire, and their handlers do their own minimal
        # checks (missing_path, empty_command, ...).
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
        # Anthropic-defined tools are declared by type+name only — passing
        # input_schema for one is rejected. Ours: flat
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
