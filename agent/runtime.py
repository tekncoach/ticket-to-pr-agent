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
    parameters: dict  # JSON Schema
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
        messages = [
            {"role": "user", "content": user_msg},
        ]
        trace = []
        for turn in range(self.max_turns):
            t0 = time.time()
            resp = self._llm(messages, tools=self._anthropic_tools())
            trace.append({"event": "llm_call", "ms": (time.time()-t0)*1000, "turn": turn})
            # if tool_calls: validate, gate side effects, append tool results
            # else: return final content + trace
            ...
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
        # wrapper, and the JSON Schema key is "input_schema", not
        # "parameters". Tool.parameters is our own field name; it becomes
        # input_schema only in the dict we hand to the API.
        return [{
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        } for t in self.tools.values()]
