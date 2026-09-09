# agent/runtime.py skeleton
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
import json, os, time

import anthropic
import jsonschema

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

    def __post_init__(self) -> None:
        # Built once per AgentRuntime instance, not once per call — the SDK
        # client holds a connection pool, no reason to recreate it per turn.
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set.")
        self._client = anthropic.Anthropic(api_key=api_key)

    def run(self, user_msg: str) -> dict:
        # Anthropic takes the system prompt as its own messages.create(system=...)
        # kwarg, not as a {"role": "system"} entry in the messages list — that
        # role is invalid there. self.system is passed straight through in _llm.
        messages: list[dict] = [
            {"role": "user", "content": user_msg},
        ]
        trace = []
        # Day 3's drill, verbatim: a repeated identical tool call is a spin,
        # not progress. The loop has no memory of its own otherwise — this
        # set is that memory, scoped to this run only. Known future
        # exception, not yet needed: a legitimate polling tool (get_ci_status)
        # would want to call itself again with the same args; not built yet,
        # so not solved yet.
        seen_calls: set[tuple[str, str]] = set()
        for turn in range(self.max_turns):
            t0 = time.time()
            resp = self._llm(messages, tools=self._anthropic_tools())
            trace.append({"event": "llm_call", "ms": (time.time() - t0) * 1000, "turn": turn})

            # Echo the assistant's own turn back into the history verbatim —
            # without this, messages never grows and the model has amnesia
            # every turn. resp.content is already the right shape (a list of
            # block objects); the SDK accepts it straight back on the next call.
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # No tool call this turn: whatever text came back is the answer.
                final_text = "".join(
                    block.text for block in resp.content if block.type == "text"
                )
                trace.append({"event": "final", "turn": turn})
                return {"answer": final_text, "trace": trace}

            # stop_reason == "tool_use": one turn can ask for several tools at
            # once. Every tool_use block needs exactly one tool_result block
            # back, and ALL of them travel together in a single user message —
            # not one message per result.
            tool_use_blocks = [b for b in resp.content if b.type == "tool_use"]
            tool_results = []
            for i, block in enumerate(tool_use_blocks):
                trace.append({
                    "event": "tool_call", "turn": turn,
                    "tool": block.name, "args": block.input,
                })

                signature = (block.name, json.dumps(block.input, sort_keys=True))
                if signature in seen_calls:
                    # Hard stop, not another error tool_result: an error result
                    # gives the model a chance to try again, which is exactly
                    # the spin we're stopping — it already got this identical
                    # call's outcome once, sending it back changes nothing.
                    trace.append({"event": "duplicate_call_stop", "turn": turn, "tool": block.name})
                    return {
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

                trace.append({
                    "event": "tool_result", "turn": turn,
                    "tool": block.name, "ok": result.ok,
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

        return {"error": "max_turns", "trace": trace}

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

    def _llm(self, messages: list[dict], tools: list[dict]) -> anthropic.types.Message:
        return self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            messages=messages,
            tools=tools,
        )

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
