# evals/judge.py
#
# The faithfulness judge, and the only thing that makes it quotable:
# a measured agreement with labels a person wrote first.
#
# A judge is an instrument. An instrument nobody compared against ground truth
# reports its own opinion in the units of a measurement, which is worse than
# reporting nothing — the number looks like evidence. So the workflow here has
# three steps and they are ordered on purpose:
#
#   --dump       write the sample as question / evidence / answer, no scores
#   (a human)    score them 1-5 in evals/judge-labels.jsonl, before seeing the judge
#   --calibrate  run the judge on the same sample and report the agreement
#
# Scoring after seeing the judge's output measures how persuasive it is, not
# whether it is right, so --dump deliberately carries no model output at all.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

import anthropic

from evals.runner import missing_fixture, run_case
from evals.schema import GoldenCase, JUDGE, load_golden
from evals.scorers import judge_prompt

HERE = Path(__file__).parent
SAMPLE_PATH = HERE / "judge-sample.jsonl"
LABELS_PATH = HERE / "judge-labels.jsonl"
REPORT_PATH = HERE / "judge-calibration.json"

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-haiku-4-5")
# The sample: every case that produces an answer a judge could grade. Retrieval
# cases have none, and agent_run cases are not started from here.
SAMPLE_TIERS = ("single_turn",)

# Answers deliberately unsupported by their own evidence, built by corrupting a
# real one. Without them the sample has no low end: this agent rarely makes
# things up on these cases, so an uncalibrated judge that answered 5 to
# everything would have agreed with every hand label and looked perfect. A
# probe is ground truth by construction — someone wrote the falsehood — and it
# is the only part of the calibration that measures detection rather than
# assent.
PROBES = (
    ("probe-figure", "invent a figure the evidence does not carry", 1,
     lambda answer: answer + "\n\nThe measured first-attempt CI pass rate is 92.4%."),
    ("probe-citation", "cite a source retrieval never returned", 2,
     lambda answer: answer + "\n\nThis is confirmed in [pinecone-scaling-guide#4.2]."),
    ("probe-flip", "assert the opposite of the evidence", 1,
     lambda answer: "The test suite is red: 3 tests failed and the run was aborted."),
    ("probe-embellish", "add a plausible detail nobody retrieved", 2,
     lambda answer: answer + "\n\nThe policy also requires a 15-minute acknowledgement window."),
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def sample_cases() -> list[GoldenCase]:
    return [c for c in load_golden()
            if c.tier in SAMPLE_TIERS and missing_fixture(c) is None]


def _judge_once(client: anthropic.Anthropic, prompt: str) -> dict:
    response = client.messages.create(
        model=JUDGE_MODEL, max_tokens=512,
        system=JUDGE, messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"score": None, "unsupported": [], "rationale": f"unparseable: {text[:200]}"}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"score": None, "unsupported": [], "rationale": f"unparseable: {text[:200]}"}


def dump() -> None:
    """Run the sample and write what a human needs to score it, nothing more."""
    rows, last_grounded = [], None
    for case in sample_cases():
        outcome = run_case(case)
        if outcome is None:
            continue
        answer = outcome.get("answer") or ""
        if not answer.strip():
            # Faithfulness is undefined on a non-answer: it makes no
            # unsupported claim, so the rubric would score it 5, which says
            # nothing about anything. The case still failed — that belongs to
            # the deterministic scorers, not to the judge.
            print(f"  skip {case.id}: no answer to grade")
            continue
        rows.append({"id": case.id, "prompt": judge_prompt(case, outcome),
                     "answer": answer, "answer_sha": _sha(answer)})
        if case.id == "tool-007":  # short, factual, fully grounded: a clean base to corrupt
            last_grounded = rows[-1]

    base = last_grounded or rows[0]
    for probe_id, what, _expected, corrupt in PROBES:
        corrupted = corrupt(base["answer"])
        rows.append({
            "id": probe_id, "probe": what,
            "prompt": base["prompt"].rsplit("ASSISTANT:\n", 1)[0] + f"ASSISTANT:\n{corrupted}\n",
            "answer": corrupted, "answer_sha": _sha(corrupted),
        })

    SAMPLE_PATH.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} samples ({len(PROBES)} probes) to {SAMPLE_PATH}")
    print(f"score each 1-5 in {LABELS_PATH.name} as "
          '{"id": "...", "score": n}, then run --calibrate')


def _agreement(pairs: list[tuple[int, int]]) -> dict:
    """Exact and within-one agreement, plus a chance-corrected kappa.

    Raw agreement on a 1-5 scale where most answers are 4s and 5s is flattered
    by the imbalance; quadratic-weighted kappa is the number that survives
    someone asking whether a judge that always says 5 would have scored the
    same.
    """
    n = len(pairs)
    exact = sum(1 for h, j in pairs if h == j) / n
    within_one = sum(1 for h, j in pairs if abs(h - j) <= 1) / n

    labels = sorted({v for pair in pairs for v in pair})
    index = {label: i for i, label in enumerate(labels)}
    k = len(labels)
    observed = [[0] * k for _ in range(k)]
    for h, j in pairs:
        observed[index[h]][index[j]] += 1
    rows = [sum(r) for r in observed]
    cols = [sum(observed[i][c] for i in range(k)) for c in range(k)]

    def weight(a: int, b: int) -> float:
        return ((labels[a] - labels[b]) ** 2) / ((labels[-1] - labels[0]) ** 2 or 1)

    num = sum(weight(a, b) * observed[a][b] for a in range(k) for b in range(k))
    den = sum(weight(a, b) * rows[a] * cols[b] / n for a in range(k) for b in range(k))
    kappa = 1 - num / den if den else None
    return {"n": n, "exact": round(exact, 3), "within_one": round(within_one, 3),
            "quadratic_kappa": round(kappa, 3) if kappa is not None else None}


def calibrate() -> int:
    samples = {json.loads(l)["id"]: json.loads(l)
               for l in SAMPLE_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    labels = {json.loads(l)["id"]: json.loads(l)
              for l in LABELS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()}
    unlabelled = set(samples) - set(labels)
    if unlabelled:
        print(f"not scored by hand yet: {sorted(unlabelled)}")
        return 1

    # The model answers differently between dumps, so a label written against
    # one answer says nothing about another. Labels carry the digest of what
    # was read; a re-dump invalidates them rather than silently relabelling.
    stale = [i for i, row in samples.items()
             if labels[i].get("answer_sha") != row.get("answer_sha")]
    if stale:
        print(f"labels were written against different answers: {sorted(stale)}")
        print("re-score them against the current judge-sample.jsonl")
        return 1

    client = anthropic.Anthropic(api_key=os.environ["LLM_API_KEY"])
    rows, pairs = [], []
    for case_id, sample in samples.items():
        verdict = _judge_once(client, sample["prompt"])
        human = labels[case_id]["score"]
        rows.append({"id": case_id, "human": human, "judge": verdict.get("score"),
                     "rationale": (verdict.get("rationale") or "")[:300],
                     "unsupported": verdict.get("unsupported") or []})
        if isinstance(verdict.get("score"), (int, float)):
            pairs.append((human, int(verdict["score"])))
        print(f"  {case_id:<12} human={human} judge={verdict.get('score')}")

    probes = [r for r in rows if r["id"].startswith("probe-")]
    caught = [r for r in probes if isinstance(r["judge"], (int, float)) and r["judge"] <= 3]
    report = {
        "judge_model": JUDGE_MODEL,
        "agreement": _agreement(pairs) if pairs else None,
        # Reported apart from agreement, because they answer different
        # questions. Agreement says the judge and a person call the same
        # grounded answers grounded; detection says it notices when one is not.
        # A judge that always answers 5 scores well on the first and zero here.
        "probe_detection": {"planted": len(probes), "caught": len(caught),
                            "missed": [r["id"] for r in probes if r not in caught]},
        "unparseable": [r["id"] for r in rows if r["judge"] is None],
        "scores": rows,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"\n{report['agreement']}\n-> {REPORT_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="The faithfulness judge and its calibration.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dump", action="store_true")
    group.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()
    if args.dump:
        dump()
        return 0
    return calibrate()


if __name__ == "__main__":
    raise SystemExit(main())
