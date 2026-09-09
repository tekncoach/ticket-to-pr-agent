# agent/runtime.py skeleton
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
import json, os, time

import anthropic

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error_code: str | None = None

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict  # JSON Schema — Anthropic's own field name, no translation needed
    handler: Callable[[dict], ToolResult]
    side_effect: bool = False

@dataclass
class AgentRuntime:
    model: str
    tools: dict[str, Tool]
    system: str
    max_turns: int = 8
    max_tokens: int = 1024
    allow_side_effects: bool = False

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
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue  # a text block can sit alongside tool_use in the same turn

                trace.append({
                    "event": "tool_call", "turn": turn,
                    "tool": block.name, "args": block.input,
                })

                tool = self.tools.get(block.name)  # .get(), not [block.name]:
                if tool is None:                   # a hallucinated tool name
                    result = ToolResult(ok=False, error_code="unknown_tool")
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

    def _llm(self, messages: list[dict], tools: list[dict]) -> anthropic.types.Message:
        return self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            messages=messages,
            tools=tools,
        )

    def _anthropic_tools(self) -> list[dict]:
        # Anthropic's Messages API takes tools flat: no "type": "function"
        # wrapper around name/description/input_schema.
        return [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        } for t in self.tools.values()]
