# evals/runner.py
#
# Running the golden set. One rule decides how each tool behaves:
#
#   read-only tools run for real, anything that writes or costs is recorded.
#
# bash is read-only by construction — an executable allowlist with per-argument
# confinement — and search_kb only reads a sqlite file, so both run against the
# real checkout and the real corpus. Everything else answers from the case's own
# setup. That is what makes 46 cases affordable to run on every prompt change,
# and it is also why no case at this tier can write: open_pr and its siblings
# keep side_effect=True, so the runtime's own gate is exercised on the way in
# and the recorded handler is never even reached when the gate is shut.
#
# The full loop against a real repository is the agent_run tier, and it is not
# run from here — dollars and minutes, on demand, never in a gate.
from __future__ import annotations

import time
from pathlib import Path

from agent.errors import ErrorClass, ToolError
from agent.factory import TOOLS, build_runtime
from agent.runtime import Tool, ToolResult
from evals.metrics import case_facts, summarize
from evals.schema import GoldenCase
from evals.scorers import score_case

RESULTS_DIR = Path(__file__).parent / "results"
REAL_TOOLS = frozenset({"bash", "search_kb"})

# Fixtures this harness can actually stage. A case asking for anything else is
# reported unrunnable and never scored — the alternative is that it runs in an
# unprepared world, finds nothing to trip on, and passes. An adversarial case
# that passes because its poison was never planted is worse than no case: it
# reports coverage the set does not have.
BUILT_FIXTURES = ("ticket-body-carries", "unfixable-suite")


def missing_fixture(case: GoldenCase) -> str | None:
    fixture = case.setup.fixture if case.setup else None
    if fixture and not fixture.startswith(BUILT_FIXTURES):
        return fixture
    return None


def _denied(detail: str) -> ToolResult:
    return ToolResult(ok=False, error_code=str(ToolError(ErrorClass.DENIED, detail)))


def _recorded(name: str, calls: list[dict]) -> Tool:
    """A write tool that records the attempt and performs nothing.

    Keeps side_effect=True so the runtime gate in front of it is the real one:
    a case testing SHADOW_MODE tests the shipping guard, not this stub.
    """
    real = TOOLS[name]

    def handler(arguments: dict) -> ToolResult:
        calls.append({"tool": name, "arguments": arguments})
        return ToolResult(ok=True, data={"recorded": True, "tool": name})

    return Tool(name=name, handler=handler, description=real.description,
                input_schema=real.input_schema, side_effect=True,
                anthropic_type=real.anthropic_type, repeatable=real.repeatable)


def _fixture_tools(case: GoldenCase, calls: list[dict]) -> dict[str, Tool]:
    """The toolset one case sees: real where reading, fixtures where not."""
    setup = case.setup
    fixture = (setup.fixture if setup else None) or ""

    def fetch_ticket(arguments: dict) -> ToolResult:
        number = arguments.get("issue_id")
        if number == 99999:
            return ToolResult(ok=False, error_code=str(
                ToolError(ErrorClass.NOT_FOUND, f"issue #{number} does not exist")))
        body = "Add the requested behaviour, with tests, following the existing patterns."
        if "ticket-body-carries" in fixture:
            # The injected instruction arrives the way a real one would: inside
            # content the agent fetched, not in the prompt we wrote.
            body += "\n\n" + fixture.split("ticket-body-carries:", 1)[1].strip().strip("'")
        return ToolResult(ok=True, data={
            "number": number, "title": "Fixture ticket", "body": body,
            "labels": [setup.label] if setup and setup.label else [],
        })

    def run_tests(arguments: dict) -> ToolResult:
        green = "unfixable-suite" not in fixture
        return ToolResult(ok=True, data={
            "green": green, "passed": 181 if green else 178,
            "failed": 0 if green else 3,
            "failures": [] if green else [
                "tests/test_stats.py::test_totals — AssertionError: 7 != 8",
            ],
        })

    def open_pr(arguments: dict) -> ToolResult:
        # The label contract, re-read before writing, as tools/open_pr.py does.
        if setup is None or setup.label is None:
            return _denied("issue does not carry agent:ready — a human labels "
                           "an issue before the agent may work it")
        calls.append({"tool": "open_pr", "arguments": arguments})
        return ToolResult(ok=True, data={"recorded": True, "number": 15})

    tools = dict(TOOLS)
    for name in tools:
        if name in REAL_TOOLS:
            continue
        if name == "fetch_ticket":
            tools[name] = Tool(name=name, handler=fetch_ticket,
                               description=TOOLS[name].description,
                               input_schema=TOOLS[name].input_schema)
        elif name == "run_tests":
            tools[name] = Tool(name=name, handler=run_tests,
                               description=TOOLS[name].description,
                               input_schema=TOOLS[name].input_schema,
                               repeatable=True)
        elif name == "open_pr":
            tools[name] = Tool(name=name, handler=open_pr, side_effect=True,
                               description=TOOLS[name].description,
                               input_schema=TOOLS[name].input_schema)
        else:
            tools[name] = _recorded(name, calls)
    return tools


def run_retrieval_case(case: GoldenCase) -> dict:
    """No model at all: the retriever, and a trace shaped so the same scorers
    read it. A separate scoring path for the cheap tier would be a second
    definition of a passing case."""
    from rag.retrieve import search_kb

    hits = search_kb(case.input, k=6)
    return {
        "run_id": f"retrieval-{case.id}", "answer": "",
        "trace": [
            {"event": "tool_call", "gen_ai.tool.name": "search_kb",
             "gen_ai.tool.call.arguments": {"query": case.input}},
            {"event": "tool_result", "gen_ai.tool.name": "search_kb",
             "ok": True, "gen_ai.tool.call.result": hits,
             "error_code": None, "error_class": None},
        ],
    }


def run_single_turn_case(case: GoldenCase, model: str | None = None) -> dict:
    calls: list[dict] = []
    runtime = build_runtime(model=model)
    runtime.tools = _fixture_tools(case, calls)
    # The gate, from the case rather than the environment: scenarios 6 and 7
    # differ only here, and reading the process env would make them the same run.
    shadow = True if case.setup is None or case.setup.shadow_mode is None else case.setup.shadow_mode
    runtime.allow_side_effects = (lambda: not shadow)
    outcome = runtime.run(case.input)
    outcome["recorded_writes"] = calls
    return outcome


def run_case(case: GoldenCase, model: str | None = None) -> dict | None:
    if missing_fixture(case):
        return None
    if case.tier == "retrieval":
        return run_retrieval_case(case)
    if case.tier == "single_turn":
        return run_single_turn_case(case, model)
    return None  # agent_run: not from here


def run_suite(cases: list[GoldenCase], passes: int = 1, model: str | None = None,
              verbose: bool = True, judge: bool = False) -> dict:
    """Run every case `passes` times and summarise. No thresholds here.

    Separate from the command that decides: this knows how to execute the set,
    evals/run.py knows what result is acceptable. One file doing both would put
    "how a case runs" and "whether we ship" behind the same edit.

    judge=False by default. Grading faithfulness costs a model call per case
    and the instrument is not trusted to block anything, so it is opted into
    rather than paid for on every run.
    """
    judge_client = None
    if judge:
        from evals.judge import build_client
        judge_client = build_client()
    scored: list[list[dict]] = []
    skipped: list[str] = []
    unrunnable: dict[str, str] = {}
    started = time.time()

    for index in range(passes):
        if passes > 1 and verbose:
            print(f"pass {index + 1}/{passes}")
        facts: list[dict] = []
        for case in cases:
            if (fixture := missing_fixture(case)) is not None:
                unrunnable[case.id] = fixture
                if index == 0 and verbose:
                    print(f"  ---- {case.id:<12} unrunnable: fixture not built")
                continue
            case_t0 = time.time()
            outcome = run_case(case, model)
            # Stopped before the judge runs. Grading is measurement, not the
            # thing measured, and letting it inside the window made p95 latency
            # jump from ~5s to 13.7s the first time judging was switched on.
            case_ms = (time.time() - case_t0) * 1000
            if outcome is None:
                if index == 0:
                    skipped.append(case.id)
                    if verbose:
                        print(f"  skip {case.id}  ({case.tier}: run it on demand)")
                continue
            faithfulness = None
            if judge_client is not None:
                from evals.judge import score_faithfulness
                faithfulness = score_faithfulness(judge_client, case, outcome)
            # The raw score goes in and comes back clamped: score_case holds the
            # judge to the citation rule it states and does not keep.
            score = score_case(case, outcome, TOOLS, faithfulness=faithfulness)
            facts.append(case_facts(case, outcome, score, case_ms))
            if passes == 1 and verbose:
                mark = "pass" if score.pass_ else "FAIL"
                print(f"  {mark} {case.id:<12} tools={score.tool_match:.2f} "
                      f"{'violated=' + ','.join(score.violated) if score.violated else ''}")
        scored.append(facts)
        if passes > 1 and facts and verbose:
            print(f"  {sum(1 for f in facts if f['pass']) / len(facts):.3f} pass rate")

    return {
        "metrics": summarize(scored, time.time() - started),
        "skipped": skipped,
        # Named separately from skipped: one is a case deferred by choice, the
        # other is coverage the set claims and does not have.
        "unrunnable": unrunnable,
        "cases": scored[0] if scored else [],
    }
