# shadow/harvest.py
#
# Traffic, from a repository we do not own.
#
# The obvious source was this project's own git history: every commit is a
# piece of work with its answer attached. It is also useless as traffic, and
# the reason is worth writing down — a ticket reconstructed from the commit
# that resolved it contains the answer. "Show the share URL as text, not only
# inside an input" is not a request, it is a summary of the fix. Replaying
# that measures how well the ticket was paraphrased.
#
# An issue written before anyone knew the answer does not have that problem.
# So the traffic is issue -> merged-PR pairs from a public repository: the
# issue text as the reporter wrote it, and the diff that closed it, which
# nobody wrote with this agent in mind.
#
# Nothing here is specific to any repository. --repo takes any of them, which
# is the point: a shadow runner coupled to its own project cannot answer the
# question a shadow run exists to ask.
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
CLOSES = re.compile(r"\b(?:closes|closed|fixes|fixed|resolves|resolved)\s+#(\d+)", re.I)
# Bots author most "closes #N" pull requests in an active repository, and a
# dependency bump is not the kind of work this agent does.
BOTS = ("dependabot", "renovate", "pre-commit-ci", "github-actions")


def gh(path: str) -> dict | list:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:200])
    return json.loads(out.stdout)


def harvest(repo: str, want: int, max_files: int, max_lines: int) -> list[dict]:
    """issue -> merged PR pairs small enough to be one unit of agent work."""
    found: list[dict] = []
    seen: set[int] = set()
    for page in range(1, 6):
        query = (f"search/issues?q=repo:{repo}+is:pr+is:merged+in:body+closes"
                 f"&per_page=50&page={page}&sort=created&order=desc")
        items = gh(query).get("items", [])
        if not items:
            break
        for item in items:
            if len(found) >= want:
                return found
            if any(bot in (item.get("user") or {}).get("login", "").lower() for bot in BOTS):
                continue
            match = CLOSES.search(item.get("body") or "")
            if not match:
                continue
            issue_no = int(match.group(1))
            if issue_no in seen:
                continue
            seen.add(issue_no)
            try:
                issue = gh(f"repos/{repo}/issues/{issue_no}")
                pull = gh(f"repos/{repo}/pulls/{item['number']}")
            except RuntimeError:
                continue
            # A pull request is not an issue, and one closing another pull
            # request is not a reported problem.
            if "pull_request" in issue or not (issue.get("body") or "").strip():
                continue
            changed = pull.get("changed_files") or 0
            touched = (pull.get("additions") or 0) + (pull.get("deletions") or 0)
            if changed > max_files or touched > max_lines:
                continue
            found.append({
                "request_id": f"{repo.replace('/', '-')}-{issue_no}",
                "repo": repo,
                "issue": issue_no,
                "title": issue["title"],
                "body": issue["body"],
                "opened_at": issue["created_at"],
                # The baseline, recorded at harvest so the pair is fixed before
                # the agent ever sees the input.
                "baseline": {
                    "source": "merged-pull-request",
                    # The paths, not just a count. Comparing "1 file" to "1
                    # file" says nothing; comparing which file says whether the
                    # agent found the same place.
                    "files": sorted(f["filename"] for f in
                                    (gh(f"repos/{repo}/pulls/{item['number']}/files"
                                        "?per_page=100") or [])),
                    "action": pull["title"],
                    "artifact": (f"PR #{pull['number']}: {changed} file(s), "
                                 f"+{pull.get('additions')}/-{pull.get('deletions')} "
                                 f"{pull['html_url']}"),
                    "at": pull.get("merged_at"),
                },
                "merge_commit": pull.get("merge_commit_sha"),
                "base_sha": (pull.get("base") or {}).get("sha"),
            })
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest shadow traffic from any repo.")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--want", type=int, default=60)
    parser.add_argument("--max-files", type=int, default=4)
    parser.add_argument("--max-lines", type=int, default=120)
    parser.add_argument("--out", type=Path, default=HERE / "traffic.jsonl")
    args = parser.parse_args()

    pairs = harvest(args.repo, args.want, args.max_files, args.max_lines)
    args.out.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
        encoding="utf-8")
    print(f"{len(pairs)} issue -> PR pairs from {args.repo} -> {args.out}")
    for p in pairs[:5]:
        print(f"  #{p['issue']:<6} {p['title'][:58]:<60} {p['baseline']['artifact'][:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
