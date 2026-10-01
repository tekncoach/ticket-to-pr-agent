# tests/test_tool_registry.py
#
# Which tools the agent has is configuration (AGENT_TOOLS), not an import list.
# The default must stay exactly what it was: all seven, same order, same prompt.
import sys
import textwrap

import pytest

from agent.runtime import Tool, ToolResult
from agent.tool_registry import BUILTIN_TOOL_NAMES, ToolConfigError, load_tools


def test_default_loads_every_builtin_in_the_historical_order():
    loaded = load_tools(None)
    assert list(loaded.tools) == [
        "bash", "comment_on_ticket", "fetch_ticket", "open_pr",
        "run_tests", "search_kb", "str_replace_based_edit_tool"]
    assert loaded.unavailable == {}
    assert tuple(loaded.tools) == BUILTIN_TOOL_NAMES


def test_blank_value_means_default_not_no_tools():
    assert list(load_tools("  ").tools) == list(BUILTIN_TOOL_NAMES)


def test_a_subset_loads_only_what_is_named():
    loaded = load_tools("fetch_ticket, search_kb")
    assert list(loaded.tools) == ["fetch_ticket", "search_kb"]


def test_an_unknown_name_fails_at_startup_and_names_the_choices():
    with pytest.raises(ToolConfigError, match="bsah") as err:
        load_tools("bash,bsah")
    assert "fetch_ticket" in str(err.value)


def test_a_duplicate_name_fails():
    with pytest.raises(ToolConfigError, match="twice"):
        load_tools("bash,bash")


@pytest.fixture
def plugin_dir(tmp_path, monkeypatch):
    (tmp_path / "plugin_tools.py").write_text(textwrap.dedent("""
        from agent.runtime import Tool, ToolResult

        echo = Tool(name="echo", handler=lambda a: ToolResult(ok=True, data=a),
                    description="echo", input_schema={"type": "object", "properties": {}})
        not_a_tool = 42
        side_effecting = Tool(name="push_it", side_effect=True,
                              handler=lambda a: ToolResult(ok=True, data="pushed"),
                              input_schema={"type": "object", "properties": {}})
        clash = Tool(name="bash", handler=lambda a: ToolResult(ok=True))
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield
    sys.modules.pop("plugin_tools", None)


def test_an_external_module_attr_loads_next_to_builtins(plugin_dir):
    loaded = load_tools("bash,plugin_tools:echo")
    assert list(loaded.tools) == ["bash", "echo"]
    assert isinstance(loaded.tools["echo"], Tool)


def test_an_external_attr_that_is_not_a_tool_fails(plugin_dir):
    with pytest.raises(ToolConfigError, match="not a Tool"):
        load_tools("plugin_tools:not_a_tool")


def test_an_external_tool_cannot_shadow_a_builtin(plugin_dir):
    with pytest.raises(ToolConfigError, match="twice"):
        load_tools("bash,plugin_tools:clash")


def test_a_required_import_failure_raises():
    with pytest.raises(ToolConfigError, match="no_such_module"):
        load_tools("no_such_module:thing")


def test_an_optional_import_failure_is_recorded_not_raised():
    loaded = load_tools("bash,no_such_module:thing?")
    assert list(loaded.tools) == ["bash"]
    assert list(loaded.unavailable) == ["no_such_module:thing"]
    assert "no_such_module" in loaded.unavailable["no_such_module:thing"]


def test_an_optional_entry_that_is_present_still_loads(plugin_dir):
    assert "echo" in load_tools("plugin_tools:echo?").tools


def test_an_optional_entry_with_a_bad_name_still_fails():
    # Optional covers a dependency that is absent, not a typo.
    with pytest.raises(ToolConfigError):
        load_tools("bsah?")


def test_the_default_prompt_is_unchanged_and_a_gap_is_announced():
    from agent.factory import SYSTEM_PROMPT, prompt_for

    assert prompt_for({}) == SYSTEM_PROMPT
    note = prompt_for({"x:y": "ModuleNotFoundError: x"})
    assert note.startswith(SYSTEM_PROMPT)
    assert "x:y" in note and "not available" in note


def test_factory_default_registry_is_the_builtin_set():
    from agent.factory import TOOLS
    assert set(TOOLS) == set(BUILTIN_TOOL_NAMES)


def test_compose_hands_the_selection_to_the_container():
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(
        (Path(__file__).parent.parent / "deploy" / "docker-compose.yml").read_text())
    env = next(iter(compose["services"].values()))["environment"]
    assert env["AGENT_TOOLS"] == "${AGENT_TOOLS:-}"


def test_toolresult_import_is_the_runtime_one():
    # Guards the plugin contract: external tools build on the runtime's own types.
    assert ToolResult(ok=True).ok


# --- the contracts the module's header claims ------------------------------

def test_a_bug_inside_an_optional_plugin_is_not_reported_as_absent(tmp_path, monkeypatch):
    # Optional covers a missing dependency. A plugin that fails for its own
    # reasons must stop the start, or "?" becomes a way to hide a broken tool.
    (tmp_path / "broken_plugin.py").write_text("raise RuntimeError('plugin bug')\n")
    (tmp_path / "attr_plugin.py").write_text("{}.nope\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(RuntimeError, match="plugin bug"):
        load_tools("broken_plugin:t?")
    with pytest.raises(AttributeError):
        load_tools("attr_plugin:t?")


def test_a_missing_attribute_on_a_present_module_is_a_missing_tool(plugin_dir):
    assert "plugin_tools:ghost" in load_tools("plugin_tools:ghost?").unavailable
    with pytest.raises(ToolConfigError, match="ghost"):
        load_tools("plugin_tools:ghost")


def test_an_external_write_tool_still_meets_the_write_gate(plugin_dir, monkeypatch):
    # The header says loading a tool does not bypass the gate. The proof is a
    # tool that arrived through the registry being refused by the real loop.
    from test_kill_switches import _drive, _results

    from agent.event_sink import NullSink
    from agent.runtime import AgentRuntime

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    tool = load_tools("plugin_tools:side_effecting").tools["push_it"]
    runtime = AgentRuntime(model="m", tools={"push_it": tool}, system="s",
                           logger=NullSink(), allow_side_effects=lambda: False)
    run = _drive(runtime, [[("push_it", {})]])
    [result] = _results(run)
    assert result["ok"] is False and result["error_class"] == "denied"


def test_an_external_tool_can_be_switched_off_like_a_builtin(plugin_dir, monkeypatch):
    from test_kill_switches import _drive, _results

    from agent.config import disabled_tools
    from agent.event_sink import NullSink
    from agent.runtime import AgentRuntime

    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    monkeypatch.setenv("DISABLED_TOOLS", "echo")
    tool = load_tools("plugin_tools:echo").tools["echo"]
    runtime = AgentRuntime(model="m", tools={"echo": tool}, system="s",
                           logger=NullSink(), disabled_tools=disabled_tools)
    [result] = _results(_drive(runtime, [[("echo", {})]]))
    assert result["error_code"] == "denied: tool disabled by operator: echo"


def test_build_runtime_hands_the_model_the_gap_note(monkeypatch):
    # prompt_for is tested above; this pins that the real constructor calls it.
    monkeypatch.setenv("LLM_API_KEY", "not-a-real-key")
    monkeypatch.setattr("agent.factory.TOOLS_UNAVAILABLE", {"x:y": "ModuleNotFoundError"})
    from agent.factory import build_runtime
    assert "x:y" in build_runtime().system


def test_health_lists_what_did_not_load(monkeypatch):
    from fastapi.testclient import TestClient

    from agent import service
    monkeypatch.setattr(service, "TOOLS_UNAVAILABLE", {"x:y": "ModuleNotFoundError: x"})
    body = TestClient(service.app).get("/health").json()
    assert body["tools_unavailable"] == {"x:y": "ModuleNotFoundError: x"}


def test_the_golden_runner_refuses_a_reduced_tool_set(monkeypatch):
    # AGENT_TOOLS exported in the shell would otherwise make every golden and
    # shadow number describe a different agent than the one deployed by default.
    from evals import runner
    monkeypatch.setattr(runner, "TOOLS", {"bash": runner.TOOLS["bash"]})
    with pytest.raises(RuntimeError, match="AGENT_TOOLS"):
        runner.require_full_tool_set()


def test_a_builtin_that_cannot_import_stops_the_start_with_the_same_error(monkeypatch):
    # Same failure class as a typo or a broken plugin: one error type to catch,
    # and the message names the entry. A bare ImportError named only a module.
    monkeypatch.setitem(__import__("agent.tool_registry", fromlist=["x"])._BUILTIN_SPECS,
                        "bash", ("no_such_module", "bash"))
    with pytest.raises(ToolConfigError, match="built-in tool 'bash'"):
        load_tools("bash")
    assert "bash" in load_tools("bash?").unavailable
