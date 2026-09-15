# evals/freeze.py
#
# Regenerating evals/golden.lock.json, and checking it without writing.
#
# It exists because the first lock was produced by a throwaway snippet, which
# makes the frozen identity of the set depend on whoever last typed it. A hash
# nobody can reproduce on demand is a number, not a freeze.
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path

from evals.schema import GOLDEN_PATH, content_hash, load_golden, split_counts

LOCK_PATH = GOLDEN_PATH.parent / "golden.lock.json"


def build_lock(version: str = "v1", frozen_at: str | None = None) -> dict:
    cases = load_golden()
    return {
        "version": version,
        "frozen_at": frozen_at or date.today().isoformat(),
        "sha256": content_hash(),
        "cases": len(cases),
        "split": split_counts(cases),
        "tier": dict(sorted(Counter(c.tier for c in cases).items())),
        "severity": dict(sorted(Counter(c.severity for c in cases).items())),
        # How much of the set is a claim about real usage rather than
        # invention. The one number that decays silently as cases are added.
        "observed_origin": sum(
            1 for c in cases if not c.origin.startswith("authored")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze or verify the golden set.")
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the lock is stale; write nothing")
    parser.add_argument("--version", default=None,
                        help="bump the frozen version, e.g. v2 (default: keep)")
    args = parser.parse_args()

    current = json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.exists() else {}
    # The date moves only when the content does. Re-running the freeze on an
    # unchanged set must be a no-op, or every run produces a spurious diff.
    fresh = build_lock(
        version=args.version or current.get("version", "v1"),
        frozen_at=None if current.get("sha256") != content_hash() else current.get("frozen_at"),
    )

    if args.check:
        if current == fresh:
            print(f"lock is current: {fresh['cases']} cases, {fresh['sha256'][:16]}")
            return 0
        print("lock is stale — run `make golden-freeze` and commit the result")
        for key in sorted(set(current) | set(fresh)):
            if current.get(key) != fresh.get(key):
                print(f"  {key}: {current.get(key)!r} -> {fresh.get(key)!r}")
        return 1

    LOCK_PATH.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    print(f"froze {fresh['cases']} cases as {fresh['version']} {fresh['sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
