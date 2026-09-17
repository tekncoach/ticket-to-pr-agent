# shadow/audit.py
#
# Proof that the batch wrote nothing, taken from the system we did not write.
#
# SHADOW_MODE is ours. The write gate is ours. The receipts saying "not
# executed" are ours. A bug anywhere in that path produces exactly the same
# reassuring output as a correct run, which is why none of it is evidence.
#
# So this asks GitHub. It records the counts that a write would move — comments
# per issue, open branches, pull requests — before a batch and after it, and
# compares. The only assertion it makes is about numbers somebody else keeps.
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent


def gh(path: str, jq: str | None = None) -> str:
    cmd = ["gh", "api", path] + (["--jq", jq] if jq else [])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return out.stdout.strip() if out.returncode == 0 else f"error: {out.stderr.strip()[:80]}"


def snapshot(repo: str, issues: list[int]) -> dict:
    """Everything a write by this agent would move, counted at the source."""
    return {
        "taken_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "repo": repo,
        "comments": {str(n): gh(f"repos/{repo}/issues/{n}/comments?per_page=100", "length")
                     for n in issues},
        "pull_requests": gh(f"repos/{repo}/pulls?state=all&per_page=100", "length"),
        "branches": gh(f"repos/{repo}/branches?per_page=100", "length"),
    }


def compare(before: dict, after: dict) -> list[str]:
    """Anything that moved. Empty is the only acceptable answer."""
    moved = []
    for issue, count in (after.get("comments") or {}).items():
        was = (before.get("comments") or {}).get(issue)
        if was != count:
            moved.append(f"issue #{issue} comments {was} -> {count}")
    for field in ("pull_requests", "branches"):
        if before.get(field) != after.get(field):
            moved.append(f"{field} {before.get(field)} -> {after.get(field)}")
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the integration whether anything was written.")
    parser.add_argument("action", choices=["before", "after"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issues", default="", help="comma-separated issue numbers to count")
    parser.add_argument("--state", type=Path, default=HERE / "audit-before.json")
    args = parser.parse_args()

    issues = [int(n) for n in args.issues.split(",") if n.strip()]

    if args.action == "before":
        args.state.write_text(json.dumps(snapshot(args.repo, issues), indent=2) + "\n",
                              encoding="utf-8")
        print(f"snapshot taken -> {args.state}")
        return 0

    if not args.state.exists():
        print(f"no snapshot at {args.state} — run `before` first, or there is nothing to compare")
        return 1

    before = json.loads(args.state.read_text(encoding="utf-8"))
    after = snapshot(args.repo, [int(k) for k in (before.get("comments") or {})])
    moved = compare(before, after)
    (HERE / "audit-after.json").write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")

    for line in moved:
        print(f"  MOVED {line}")
    print(f"\n{'nothing moved — the batch wrote nothing' if not moved else 'THE SHADOW PATH WROTE SOMETHING'}"
          f"  ({before['taken_at']} -> {after['taken_at']})")
    return 1 if moved else 0


if __name__ == "__main__":
    raise SystemExit(main())
