# agent/tool_registry.py
#
# Which tools the agent has is configuration, not an import list.
#
# AGENT_TOOLS is a comma-separated list. Each entry is either a built-in name
# ("bash") or "module:attr" for a Tool defined outside this repo. A trailing "?"
# marks an entry optional: if its import fails the agent starts without it and
# says so (on /health and in the system prompt) instead of refusing to start.
# Unset or blank means every built-in, which is what the agent always had.
#
# Three things this deliberately does not do:
#   - guess: an unknown name is an error at startup, never a silent skip. A typo
#     that quietly removes a tool is a worse failure than one that stops the boot.
#   - hide a missing required tool: only "?" entries may be absent.
#   - touch the write gate: every loaded tool still passes through the runtime's
#     side_effect, shadow-mode and disabled-tools checks.
from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from agent.runtime import Tool

# Historical order, and the names evals/schema.py's ToolName mirrors.
_BUILTIN_SPECS: dict[str, tuple[str, str]] = {
    "bash": ("tools.bash", "bash"),
    "comment_on_ticket": ("tools.comment_on_ticket", "comment_on_ticket"),
    "fetch_ticket": ("tools.fetch_ticket", "fetch_ticket"),
    "open_pr": ("tools.open_pr", "open_pr"),
    "run_tests": ("tools.run_tests", "run_tests"),
    "search_kb": ("tools.search_kb", "search_kb"),
    "str_replace_based_edit_tool": ("tools.edit_file", "edit_file"),
}
BUILTIN_TOOL_NAMES = tuple(_BUILTIN_SPECS)


class ToolConfigError(ValueError):
    """AGENT_TOOLS names something that cannot be loaded as configured."""


@dataclass
class LoadedTools:
    tools: dict[str, Tool]
    # spec -> why it is absent. Only optional entries can land here.
    unavailable: dict[str, str] = field(default_factory=dict)


def _import(module: str, attr: str):
    """ImportError means the module (or a dependency of it) is absent.

    The attribute lookup is split from the import on purpose: an AttributeError
    raised INSIDE a plugin's own top-level code is a bug in the plugin, and
    swallowing it as "optional tool unavailable" would hide it. Only a missing
    name on a module that imported fine counts as a missing tool.
    """
    mod = importlib.import_module(module)
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise ImportError(f"module {module!r} has no attribute {attr!r}") from e


def load_tools(spec: str | None) -> LoadedTools:
    entries = [e.strip() for e in (spec or "").split(",") if e.strip()]
    if not entries:
        entries = list(BUILTIN_TOOL_NAMES)

    tools: dict[str, Tool] = {}
    unavailable: dict[str, str] = {}
    seen: set[str] = set()
    for entry in entries:
        optional = entry.endswith("?")
        ref = entry.rstrip("?").strip()
        if ref in seen:
            raise ToolConfigError(f"AGENT_TOOLS names {ref!r} twice")
        seen.add(ref)

        if ":" in ref:
            module, _, attr = ref.partition(":")
            try:
                tool = _import(module, attr)
            except ImportError as e:
                if not optional:
                    raise ToolConfigError(
                        f"AGENT_TOOLS entry {ref!r} cannot be imported "
                        f"({type(e).__name__}: {e}); add '?' to make it optional") from e
                unavailable[ref] = f"{type(e).__name__}: {e}"
                continue
            if not isinstance(tool, Tool):
                raise ToolConfigError(f"AGENT_TOOLS entry {ref!r} is not a Tool")
            registered = tool.name
        elif ref in _BUILTIN_SPECS:
            module, attr = _BUILTIN_SPECS[ref]
            try:
                tool = _import(module, attr)
            except ImportError as e:
                if not optional:
                    raise
                unavailable[ref] = f"{type(e).__name__}: {e}"
                continue
            registered = ref
        else:
            raise ToolConfigError(
                f"AGENT_TOOLS names {ref!r}, which is not a built-in tool "
                f"({', '.join(BUILTIN_TOOL_NAMES)}) or a 'module:attr' reference")

        if registered != ref and ":" not in ref:
            raise ToolConfigError(f"built-in {ref!r} carries the name {registered!r}")
        if registered in tools:
            raise ToolConfigError(f"AGENT_TOOLS loads the tool name {registered!r} twice")
        tools[registered] = tool
    return LoadedTools(tools=tools, unavailable=unavailable)
