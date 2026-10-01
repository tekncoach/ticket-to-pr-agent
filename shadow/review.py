# shadow/review.py
#
# The adjudication queue as a page a person can read.
#
# adjudications.json is where the judgements live, and it is a poor place to
# read them: every case is a block of keys, the reason is one long line, and
# nothing says which of the thirty are still waiting. This renders the same
# data, grouped by who was right, with the ticket title and the files beside
# each reason. It reads the JSON and never writes it — change a winner in
# adjudications.json and run this again.
#
#   python -m shadow.review            # writes shadow/review.html
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
REPO = "encode/httpx"

# (key, heading, one line saying what it means)
GROUPS = [
    ("agent-correct", "L'agent avait raison",
     "Sa proposition vaut celle de l'humain, ou mieux."),
    ("ambiguous", "Ambigu",
     "Le ticket ou le correctif humain ne permet pas de trancher."),
    ("baseline-correct", "L'humain avait raison",
     "La proposition de l'agent est absente, fausse ou incomplète."),
    ("both-wrong", "Les deux se trompent",
     "Ni la proposition de l'agent ni le correctif humain ne règlent le ticket."),
]

STOPS = {
    "allowlist_workaround": "bloqué : commande hors liste",
    "duplicate_tool_call": "bloqué : même appel répété",
    "max_turns": "bloqué : trop de tours",
    "repeated_tool_failure": "bloqué : échecs répétés",
}


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def files(paths: list[str]) -> str:
    if not paths:
        return '<span class="none">aucun</span>'
    return "".join(f"<code>{esc(p)}</code>" for p in paths)


def load():
    queue = json.loads((HERE / "adjudications.json").read_text(encoding="utf-8"))
    summary = json.loads((HERE / "summary.json").read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in summary["rows"]}
    traffic = {}
    for line in (HERE / "traffic.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            unit = json.loads(line)
            traffic[unit["request_id"]] = unit
    results = {}
    for line in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            results[record["request_id"]] = record
    return queue, rows, traffic, results, summary


def case(case_id, entry, row, unit, record) -> str:
    number = case_id.rsplit("-", 1)[-1]
    artifact = unit["baseline"]["artifact"]
    pr_url = artifact.split(" http", 1)[1] if " http" in artifact else ""
    pr_url = ("http" + pr_url) if pr_url else ""
    wrote = len(record.get("would_write") or [])
    unsafe = row["unsafe"]
    outside = unsafe["source"] + unsafe["tests"]

    badges = []
    if not wrote:
        badges.append('<span class="badge muted">n\'a rien écrit</span>')
    if outside or unsafe["forbidden_tools"]:
        badges.append('<span class="badge danger">écrit hors du périmètre</span>')
    if row["stopped_on"]:
        badges.append(f'<span class="badge muted">{esc(STOPS.get(row["stopped_on"], row["stopped_on"]))}</span>')
    if entry.get("call") == "half-the-fix":
        badges.append('<span class="badge muted">compte comme accord partiel</span>')
    elif entry.get("call") == "coincidental":
        badges.append('<span class="badge muted">ne compte pas comme accord</span>')
    badges.append(f'<span class="badge muted">{esc(row["tags"]["area"])} · {esc(row["tags"]["size"])}</span>')

    return f"""
    <article class="case">
      <header>
        <a class="num" href="https://github.com/{REPO}/issues/{esc(number)}">#{esc(number)}</a>
        <h3>{esc(unit["title"])}</h3>
      </header>
      <p class="badges">{"".join(badges)}</p>
      <p class="why">{esc(entry.get("why"))}</p>
      <dl class="files">
        <div><dt>L'humain a modifié
              {f'<a href="{esc(pr_url)}">la PR</a>' if pr_url else ""}</dt>
             <dd>{files([f for f in (unit["baseline"].get("files") or []) if not f.endswith("CHANGELOG.md")])}</dd></div>
        <div><dt>L'agent a modifié</dt>
             <dd>{files(sorted({re.sub(r".*/clones/[^/]+/", "", w["arguments"].get("path", "")) for w in record.get("would_write") or []}))}</dd></div>
      </dl>
    </article>"""


def render() -> str:
    queue, rows, traffic, results, summary = load()
    read = {k: v for k, v in queue.items() if v.get("winner")}
    waiting = {k: v for k, v in queue.items() if not v.get("winner")}

    sections = []
    for key, heading, meaning in GROUPS:
        members = [k for k, v in read.items() if v["winner"] == key]
        if not members:
            continue
        body = "".join(case(k, read[k], rows[k], traffic[k], results[k]) for k in members)
        sections.append(f"""
  <section>
    <h2><span class="dot {key}"></span>{esc(heading)} <span class="count">{len(members)}</span></h2>
    <p class="meaning">{esc(meaning)}</p>{body}
  </section>""")

    waiting_rows = "".join(
        f"""<tr><td><a href="https://github.com/{REPO}/issues/{esc(k.rsplit('-', 1)[-1])}">#{esc(k.rsplit('-', 1)[-1])}</a></td>
            <td>{esc(traffic[k]["title"])}</td>
            <td>{esc(STOPS.get(rows[k]["stopped_on"], rows[k]["stopped_on"] or "a terminé"))}</td></tr>"""
        for k in waiting)

    counts = {key: sum(1 for v in read.values() if v["winner"] == key) for key, _, _ in GROUPS}
    bar = "".join(f'<span class="seg {k}" style="flex:{n}" title="{n}"></span>'
                  for k, n in counts.items() if n)
    review = summary["review"]

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relecture des désaccords — shadow</title>
<style>
:root {{
  --bg: #fbfaf8; --surface: #ffffff; --text: #1d1f23; --muted: #62666e; --line: #e4e1db;
  --agent: #1f7a4d; --human: #2c5f9e; --ambiguous: #a86a00; --both: #b3342b;
  --danger-bg: #fbe9e7; --danger-text: #8f2a22; --chip: #f0eee9;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #15171a; --surface: #1c1f23; --text: #e8e6e1; --muted: #9a9ea6; --line: #2d3036;
    --agent: #4cb782; --human: #6ea1e0; --ambiguous: #e0a23a; --both: #ef7b72;
    --danger-bg: #3a1f1c; --danger-text: #f2a39c; --chip: #262a30;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }}
main {{ max-width: 46rem; margin: 0 auto; padding: 2.5rem 1rem 4rem; }}
h1 {{ font-size: 1.6rem; line-height: 1.2; margin: 0 0 .4rem; text-wrap: balance; }}
.lede {{ color: var(--muted); margin: 0 0 1.4rem; max-width: 40rem; }}
.bar {{ display: flex; height: .6rem; border-radius: .3rem; overflow: hidden; gap: 2px; margin-bottom: .6rem; }}
.seg.agent-correct {{ background: var(--agent); }} .seg.baseline-correct {{ background: var(--human); }}
.seg.ambiguous {{ background: var(--ambiguous); }} .seg.both-wrong {{ background: var(--both); }}
.legend {{ display: flex; flex-wrap: wrap; gap: .4rem 1.2rem; margin: 0 0 2.4rem; padding: 0; list-style: none;
  font-size: .9rem; color: var(--muted); }}
.dot {{ display: inline-block; width: .65rem; height: .65rem; border-radius: 50%; margin-right: .45rem; }}
.dot.agent-correct {{ background: var(--agent); }} .dot.baseline-correct {{ background: var(--human); }}
.dot.ambiguous {{ background: var(--ambiguous); }} .dot.both-wrong {{ background: var(--both); }}
section {{ margin-bottom: 3rem; }}
h2 {{ font-size: 1.15rem; margin: 0 0 .15rem; display: flex; align-items: center; }}
.count {{ margin-left: .5rem; color: var(--muted); font-weight: 400; font-variant-numeric: tabular-nums; }}
.meaning {{ margin: 0 0 1rem; color: var(--muted); font-size: .92rem; }}
.case {{ padding: 1.1rem 0; border-top: 1px solid var(--line); }}
.case header {{ display: flex; gap: .75rem; align-items: baseline; }}
.num {{ font: 600 .95rem var(--mono); color: var(--muted); text-decoration: none; flex: none; }}
.num:hover {{ text-decoration: underline; }}
h3 {{ font-size: 1.02rem; margin: 0; line-height: 1.35; }}
.badges {{ display: flex; flex-wrap: wrap; gap: .35rem; margin: .5rem 0 .7rem; padding: 0; }}
.badge {{ font-size: .76rem; padding: .08rem .55rem; border-radius: 1rem; background: var(--chip); color: var(--muted); }}
.badge.danger {{ background: var(--danger-bg); color: var(--danger-text); font-weight: 600; }}
.why {{ margin: 0 0 .8rem; max-width: 40rem; }}
.files {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: .6rem 1.5rem; margin: 0; }}
.files dt {{ font-size: .76rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: .2rem; }}
.files dt a {{ text-transform: none; letter-spacing: 0; margin-left: .3rem; color: var(--muted); }}
.files dd {{ margin: 0; display: flex; flex-direction: column; gap: .15rem; }}
code {{ font: .82rem var(--mono); overflow-wrap: anywhere; }}
.none {{ color: var(--muted); font-style: italic; font-size: .85rem; }}
.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: .92rem; }}
td {{ padding: .5rem .6rem .5rem 0; border-top: 1px solid var(--line); vertical-align: top; }}
td:first-child {{ font: .88rem var(--mono); white-space: nowrap; }}
td:last-child {{ color: var(--muted); font-size: .85rem; }}
td a {{ color: inherit; text-decoration: none; }} td a:hover {{ text-decoration: underline; }}
footer {{ color: var(--muted); font-size: .88rem; border-top: 1px solid var(--line); padding-top: 1rem; }}
footer code {{ background: var(--chip); padding: .05rem .3rem; border-radius: .25rem; }}
a:focus-visible {{ outline: 2px solid var(--human); outline-offset: 2px; }}
</style>
</head>
<body>
<main>
  <h1>{review["reviewed"]} désaccords relus sur {review["disagreements"]}</h1>
  <p class="lede">À chaque fois que l'agent n'a pas fait comme l'ingénieur humain, on lit les deux
  corrections et on dit qui avait raison. Les {review["reviewed"]} relus sont choisis, pas tirés
  au hasard : ils disent de quelle nature sont les échecs, pas leur fréquence.</p>
  <div class="bar" role="img" aria-label="Répartition des verdicts">{bar}</div>
  <ul class="legend">
    {"".join(f'<li><span class="dot {k}"></span>{esc(h)} {counts[k]}</li>' for k, h, _ in GROUPS)}
  </ul>
{"".join(sections)}
  <section>
    <h2>Pas encore relus <span class="count">{len(waiting)}</span></h2>
    <p class="meaning">Aucun verdict pour l'instant. Presque tous sont des runs arrêtés par un garde-fou.</p>
    <div class="table-wrap"><table>{waiting_rows}</table></div>
  </section>
  <footer>
    Pour changer un verdict : ouvre <code>shadow/adjudications.json</code>, modifie le champ
    <code>winner</code> du cas (<code>agent-correct</code>, <code>baseline-correct</code>,
    <code>both-wrong</code> ou <code>ambiguous</code>), puis relance
    <code>python -m shadow.review</code>. Cette page est générée, elle ne sert qu'à lire.
  </footer>
</main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the adjudication queue as HTML.")
    parser.add_argument("--out", type=Path, default=HERE / "review.html")
    args = parser.parse_args()
    args.out.write_text(render(), encoding="utf-8")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
