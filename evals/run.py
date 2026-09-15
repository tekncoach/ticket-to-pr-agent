# evals/run.py fragment
import json, time
from pathlib import Path
from evals.score import score_case
from evals.gates import check_gates

def main():
    cases = [json.loads(l) for l in Path("evals/golden.jsonl").read_text().splitlines() if l.strip()]
    results = []
    t0 = time.time()
    for c in cases:
        out = agent.run(c["input"], mode="eval")  # no side effects
        results.append(score_case(c, out))
    report = summarize(results, elapsed=time.time()-t0)
    out_path = Path("evals/results") / f"{int(time.time())}.json"
    out_path.write_text(json.dumps(report, indent=2))
    Path("evals/results/latest.json").write_text(out_path.read_text())
    ok, msgs = check_gates(report)
    print(json.dumps({"pass": ok, "msgs": msgs, "metrics": report["metrics"]}, indent=2))
    raise SystemExit(0 if ok else 1)
