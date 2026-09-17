# evals/promote.py
#
# The promotion path: a failure becomes a tracked mode, a tracked mode becomes
# a closed one only when a test says so.
#
# Without this the taxonomy is a spreadsheet. Three modes had sat in it marked
# FIXED with nothing proving it, and two more — F2 and F4 — had been triaged
# once and silently never fixed at all; F4 had been matching a string the wire
# never sends, so it had never fired, including on a real bypass. That is what
# "without a linked eval case, the word 'fixed' is an opinion" looks like from
# the inside.
#
# Three things this does, all of them refusals to take a word for it:
#
#   --check    every closed or witnessed mode names a test that exists; every
#              mode names a case that exists; no mode is both closed and
#              unpinned, and no open mode claims a pin it does not have.
#   --triage   failures in the latest run that no row covers, printed as CSV
#              rows ready to paste. This is the promotion step, and it is the
#              one that has to be cheap or it stops happening.
#   (default)  the standing report: what is open, closed, accepted.
#
# "witnessed" is the fourth status, and it exists because a shadow run found
# two modes that are real, reproducible and not fixed. "open" forbids a pin,
# which left them with nothing a future fix could prove itself against;
# "closed" would have been a lie. A witnessed mode names a test that pins the
# CURRENT behaviour — the behaviour we do not want — so the day it changes,
# that test either changes with a stated reason or the fix did not land.
#
# What it does NOT do is promote from production traffic, because there is
# none. The inputs are the golden set and the replay corpus, and saying so is
# the difference between a pipeline and a diagram of one.
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

SHEET = Path(__file__).parent / "failure-modes.csv"
RESULTS = Path(__file__).parent / "results"
TESTS = Path(__file__).parent.parent / "tests"

STATUSES = ("open", "witnessed", "closed", "known")


def load_sheet(path: Path = SHEET) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _test_exists(node_id: str) -> bool:
    """Whether a pytest node id names a test that is actually there.

    A grep, not a collection run: the sheet is checked by a unit test, and a
    unit test that shells out to pytest to verify pytest is a loop.
    """
    if "::" not in node_id:
        return False
    file_part, name = node_id.split("::", 1)
    path = TESTS.parent / file_part
    return path.exists() and f"def {name}(" in path.read_text(encoding="utf-8")


def check(rows: list[dict]) -> list[str]:
    """Everything the sheet claims that can be verified. Empty means clean."""
    from evals.schema import load_golden

    problems: list[str] = []
    known_cases = {c.id for c in load_golden()}
    from evals.judge import PROBES

    known_cases |= {p[0] for p in PROBES}

    for row in rows:
        mode, status = row["mode"], row.get("status", "")
        if status not in STATUSES:
            problems.append(f"{mode}: status {status!r} is not one of {STATUSES}")
        if row["case_id"] not in known_cases:
            problems.append(f"{mode}: case {row['case_id']!r} does not exist")
        if status in ("closed", "witnessed"):
            pin = row.get("pinned_by", "")
            if not pin:
                problems.append(f"{mode}: {status} with nothing pinning it")
            elif not _test_exists(pin):
                problems.append(f"{mode}: pinned by {pin!r}, which is not there")
        elif row.get("pinned_by"):
            problems.append(f"{mode}: {status} but claims a pin")
    return problems


def triage(rows: list[dict], report_path: Path) -> list[str]:
    """Failures in a run that no row in the sheet covers.

    The promotion step. A failure nobody has written down is indistinguishable
    from one nobody has noticed.
    """
    report = json.loads(report_path.read_text(encoding="utf-8"))
    cases = report.get("cases") or report.get("scores") or []
    covered = {r["case_id"] for r in rows}
    stamp = report.get("run_at", report_path.stem)
    candidates = []
    for case in cases:
        if case.get("pass") or case["id"] in covered:
            continue
        violated = ",".join(case.get("violated") or []) or "no violation, expectation unmet"
        candidates.append(
            f'F??,{case["id"]},TBD,{case.get("severity", "P1")},open,,'
            f'{stamp},"{violated}",TBD')
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="The failure-mode promotion path.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--triage", type=Path, default=RESULTS / "latest.json")
    parser.add_argument("--from-run", action="store_true",
                        help="print rows for failures the sheet does not cover")
    args = parser.parse_args()

    rows = load_sheet()

    if args.check:
        problems = check(rows)
        for problem in problems:
            print(f"  {problem}")
        print(f"{'sheet is consistent' if not problems else f'{len(problems)} problems'}"
              f" — {len(rows)} rows, {len({r['mode'] for r in rows})} modes")
        return 1 if problems else 0

    if args.from_run:
        candidates = triage(rows, args.triage)
        print(f"# uncovered failures in {args.triage.name}")
        for row in candidates:
            print(row)
        if not candidates:
            print("# none — every failure in that run is already a tracked mode")
        return 0

    by_status: dict[str, set] = {}
    for row in rows:
        by_status.setdefault(row.get("status", "?"), set()).add(row["mode"])
    for status in STATUSES:
        modes = sorted(by_status.get(status, set()),
                       key=lambda m: int(m.lstrip("F") or 0))
        print(f"{status:<9} {len(modes):>2}  {' '.join(modes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
