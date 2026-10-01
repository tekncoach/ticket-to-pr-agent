# shadow/equivalence.py
#
# Answer equivalence: does what the agent said mean what the engineer's pull
# request says?
#
# The shadow comparison is about files. This is the other half the readout
# asks for, and it is the weakest measure here, so it is built to say how weak
# it is. The baseline carries a pull request title and body, not an answer
# written for this question, so the comparison is a summary against a
# description. An embedding cosine can tell two texts are about the same thing;
# it cannot tell that one of them is right.
#
# Given that, a bare similarity number would mean nothing. Each agent answer is
# also scored against every OTHER unit's pull request text. If an answer is not
# closer to its own pull request than to the rest, the measure is not telling
# these units apart and the number should not be read.
#
# Only units that finished and wrote something are scored. A guard-stop
# sentence or "Let me implement:" is not an answer to compare.
#
#   uv run --env-file .env python -m shadow.equivalence
from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
from pathlib import Path

from rag.embeddings import embed

HERE = Path(__file__).parent
MODEL = "BAAI/bge-m3"
MAX_CHARS = 1500


def pr_text(repo: str, number: str) -> str:
    out = subprocess.run(["gh", "api", f"repos/{repo}/pulls/{number}",
                          "--jq", '"\\(.title)\\n\\n\\(.body // "")"'],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()[:MAX_CHARS]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return float(dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))))


def main() -> int:
    traffic = {u["request_id"]: u for u in map(json.loads, (HERE / "traffic.jsonl").read_text().splitlines()) if u}
    results = {r["request_id"]: r for r in map(json.loads, (HERE / "results.jsonl").read_text().splitlines()) if r}
    verdicts = {r["id"]: r["verdict"] for r in json.loads((HERE / "summary.json").read_text())["rows"]}

    units = [i for i, r in results.items()
             if not r["agent_proposal"]["stopped_on"] and r["agent_proposal"]["files_touched"]
             and not r.get("tree_error")]
    answers = [results[i]["agent_proposal"]["answer"][:MAX_CHARS] for i in units]
    texts = []
    for i in units:
        number = re.search(r"PR #(\d+)", traffic[i]["baseline"]["artifact"]).group(1)
        texts.append(pr_text(traffic[i]["repo"], number))

    vectors = embed(answers + texts, MODEL)
    a_vecs, t_vecs = vectors[:len(units)], vectors[len(units):]

    rows, own_best = [], 0
    for k, unit in enumerate(units):
        sims = [cosine(a_vecs[k], t_vecs[j]) for j in range(len(units))]
        own = sims[k]
        others = [s for j, s in enumerate(sims) if j != k]
        best_is_own = own >= max(others)
        own_best += best_is_own
        rows.append({"id": unit, "verdict": verdicts.get(unit), "cosine": round(own, 3),
                     "mean_vs_other_prs": round(statistics.mean(others), 3),
                     "closest_to_own_pr": best_is_own})

    summary = {
        "model": MODEL,
        "units": len(units),
        "median_cosine": round(statistics.median(r["cosine"] for r in rows), 3),
        "median_vs_other_prs": round(statistics.median(r["mean_vs_other_prs"] for r in rows), 3),
        "closest_to_own_pr": f"{own_best}/{len(units)}",
        "by_verdict": {v: round(statistics.median(r["cosine"] for r in rows if r["verdict"] == v), 3)
                       for v in sorted({r["verdict"] for r in rows})},
        "rows": rows,
    }
    (HERE / "equivalence.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"{len(units)} units that finished and wrote something")
    print(f"  median cosine to own PR        {summary['median_cosine']}")
    print(f"  median cosine to other PRs     {summary['median_vs_other_prs']}   <- the floor")
    print(f"  answer closest to its own PR   {summary['closest_to_own_pr']}")
    print(f"  median by verdict              {summary['by_verdict']}")
    for r in rows:
        print(f"    {r['id']:<20} {str(r['verdict']):<10} own {r['cosine']}  others {r['mean_vs_other_prs']}"
              f"  {'own is closest' if r['closest_to_own_pr'] else 'NOT closest'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
