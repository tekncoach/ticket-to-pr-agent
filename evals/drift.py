# evals/drift.py
def compare(baseline: dict, latest: dict) -> list[str]:
    alerts = []
    b, l = baseline["metrics"], latest["metrics"]
    if l["pass_rate"] < b["pass_rate"] - 0.03:
        alerts.append(f"pass_rate drift: {b['pass_rate']:.2f} -> {l['pass_rate']:.2f}")
    ...
    return alerts
