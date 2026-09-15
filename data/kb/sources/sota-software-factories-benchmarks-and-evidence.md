# State of the art: benchmarks and what the evidence actually shows

**As of 13 August 2026.** The most important file of the four, because this is
where vendor claims and independent measurement disagree most sharply — and
where a factory design either survives contact with reality or doesn't.

Source discipline: *(vendor)*, *(primary)*, *(secondary)*, *(unverified)*.

---

## 1. The headline numbers, side by side

| Measurement | Number | Source type | Date |
|---|---|---|---|
| Best agent+model, Terminal-Bench 2.1 | **83.8%** (Claude Code + Fable 5) | primary leaderboard | 7 Jun 2026 |
| Best agent+model, FrontierCode 1.1 Main | **42.3%** (SWE-1.7) | vendor benchmark, vendor model | 8 Jul 2026 |
| SWE-bench Verified, top cluster | **80–95%** self-reported on vendor scaffolds | secondary | Jun 2026 |
| Devin's own stated task ceiling | **~3 hours** | primary docs | 2026 |
| Share of dev work that uses AI | **~60%** | vendor report | 2026 |
| Share of dev work **fully delegable** | **0–20%** | vendor report | 2026 |
| METR RCT, experienced OSS devs | **19% *slower*** with AI | independent, peer-reviewed-adjacent | Jul 2025 |
| METR follow-up estimate | **~18% faster** | independent, contested design | early 2026 |
| Time-horizon doubling rate | **~89 days** since 2024 | independent | Jan 2026 |

Every one of these is defensible. Together they do not tell a coherent story,
and the incoherence is the finding.

---

## 2. SWE-bench: what happened to the field's reference benchmark

SWE-bench Verified made model evaluation legible in 2024–2025, and by mid-2026
it is effectively dead as a discriminator at the frontier.

**OpenAI's Frontier Evals team publicly stopped reporting it.** Their post is
titled, unambiguously, *"Why SWE-bench Verified no longer measures frontier
coding capabilities"*
(https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/).
**I could not fetch this page — openai.com returned HTTP 403 to my fetches on
13 August 2026 — so the following details are secondary and should be verified
against the original before you quote them:** an internal audit of 138
problematic tasks reportedly found >60% unsolvable as written due to flawed
tests, and frontier models could reproduce gold-patch solutions from the task
ID alone
*(secondary, [digitalapplied](https://www.digitalapplied.com/blog/llm-benchmark-methodology-2026-contamination-leaderboard-guide))*.

Independent contamination research points the same way: one study reports
**32.67% of successful SWE-bench Verified patches involved solution leakage**,
with models recalling correct file paths from training data up to 76% of the
time *(secondary, relayed via
[benchmarkingagents](https://benchmarkingagents.com/benchmark-contamination/);
I did not reach the underlying paper)*. The decontamination-focused
**SWE-rebench** pipeline exists precisely to address this
([primary paper](https://arxiv.org/pdf/2505.20411)).

**SWE-bench Pro** (Scale AI) is the harder successor: 1,865 tasks (731 public,
858 held-out, 276 commercial) across 41 repos in Python/Go/TypeScript/JavaScript,
averaging 107.4 lines changed, and it **knocks roughly 20–25 points off the same
models** that score highly on Verified *(secondary,
[buildmvpfast](https://www.buildmvpfast.com/blog/benchmark-contamination-ai-coding-leaderboard-swe-bench-2026))*.

**Practical consequence:** any 2026 vendor claim quoting SWE-bench Verified
without naming the scaffold, the effort setting and the decontamination method
should be read as marketing. Several still do — including numbers cited in this
document (Grok Build's 70.8%, OpenHands' 72%). I am reporting them because they
are what the sources say, not because they mean much.

---

## 3. Terminal-Bench: the current honest leaderboard

Terminal-Bench 2.0 launched November 2025 with 89 curated tasks, each given
~3 reviewer-hours of human auditing for solvability and specification quality;
each task is attempted 5 times per agent *(secondary,
[explainx](https://explainx.ai/blog/terminal-bench-2-0-ai-agent-benchmark-evaluation))*.
Version 2.1 is the current board.

**Top of the Terminal-Bench 2.1 leaderboard**
([primary](https://www.tbench.ai/leaderboard/terminal-bench/2.1), read 13 Aug 2026):

| # | Agent | Model | Score | Date |
|---|---|---|---|---|
| 1 | Claude Code | Fable 5 | 83.8% ± 1.2 | 7 Jun 2026 |
| 2 | Codex | GPT-5.5 | 83.1% ± 1.1 | 1 May 2026 |
| 3 | Terminus 2 | Fable 5 | 80.4% ± 1.2 | 5 Jun 2026 |
| 4 | Cursor CLI | Grok 4.5 | 79.3% ± 1.5 | 9 Jul 2026 |
| 5 | Claude Code | Opus 4.8 | 78.9% ± 1.3 | 9 Jul 2026 |
| 6 | Codex | GPT-5.6 Terra | 78.4% ± 1.3 | 11 Jul 2026 |
| 7 | Terminus 2 | GPT-5.5 | 78.0% ± 1.2 | 1 May 2026 |
| 8 | **mini-SWE-agent** | Muse Spark 1.1 | **76.2% ± 1.2** | 9 Jul 2026 |
| 9 | Codex | GPT-5.6 Luna | 75.7% ± 1.3 | 11 Jul 2026 |
| 10 | Claude Code | Sonnet 5 | 74.6% ± 1.6 | 9 Jul 2026 |

Methodology notes from the same page: submissions may not modify timeouts or
resources; results are verified by Terminal-Bench team members; effort levels
run high-to-maximum; and **run costs span \$134–\$599**.

Three things fall out of this table, and they are the most useful facts in this
document:

**(a) The scaffold is worth ~7 points, not 40.** mini-SWE-agent — ~100 lines of
Python, bash as its only tool, no tool-calling interface
([primary](https://github.com/SWE-agent/mini-swe-agent)) — sits at 76.2%,
7.6 points below the best commercial harness on the board and *above* Claude
Code running Sonnet 5. Every dollar of harness engineering in the industry is
buying that gap. This is the single strongest argument against building your own
harness, and also against paying a large premium for someone else's.

**(b) The error bars overlap.** Ranks 1 and 2 differ by 0.7 points with ±1.1–1.2
confidence intervals. Ranks 3 through 7 are statistically one cluster. Anyone
telling you a specific agent is "the best" in August 2026 is reading noise.

**(c) A benchmark run costs \$134–\$599.** At maximum effort, on 89 tasks. That
is \$1.50–\$6.70 per task, on tasks that were curated to be solvable. Budget
accordingly, and note that this is the *lower* bound for real work, because real
tasks are not curated for solvability.

---

## 4. FrontierCode: the benchmark that changed the question

Cognition introduced FrontierCode on **8 June 2026**, and it is the most
important benchmark development of the year because it stopped asking "does the
code pass" and started asking **"would the maintainer merge this?"**

From the primary sources
([leaderboard](https://cognition.com/frontiercode),
[1.1 post](https://cognition.com/blog/frontier-code-1.1), 7 July 2026):

- **Mergeability** is the measured quantity: correctness *plus* test quality,
  scope discipline, style, and adherence to codebase standards.
- Tasks are **built by the actual open-source maintainers of the repos** —
  20+ developers, **>40 hours per task** — each paired with maintainer-defined
  success criteria. Every task is then manually reviewed by a Cognition
  researcher, with adversarial testing and multi-stage calibration.
- Grading is an **ensemble**: unit tests, rubrics, and new verifier types. Over
  **1,000 grading criteria** exist; in 1.1 they audited all of them and relaxed
  75 that were unfairly strict.
- Some criteria are **blockers** — failing one caps the score, mirroring real
  review.
- **Internet use is permitted but policed**: a prompt defines fair use, and a
  programmatic verifier detects references to the upstream PR or
  solution-bearing mirrors. Runs that consult them **score zero**. They report
  unfair-use rates below 1% with these safeguards.
- The **Diamond subset (50 hardest tasks) was removed in 1.1** because results
  at extreme difficulty were "inherently noisy." Remaining: Main (100 tasks) and
  Extended (150).

**The number that matters: the best score on FrontierCode 1.1 Main is 42.3%**
(SWE-1.7, *(vendor)*, [primary](https://cognition.com/blog/swe-1-7)). The same
model scores **81.5%** on Terminal-Bench 2.1.

That 42.3% versus 81.5% gap, from one vendor on one model on one day, is the
most honest single data point in this entire document. **Roughly half of the
work an agent completes successfully is work a maintainer would not merge.**

Two caveats, stated plainly. First, FrontierCode is **Cognition's benchmark,
scored by Cognition, topped by Cognition's model** — a structure the field
should be sceptical of on principle, whatever the methodology. Second, I could
not read the full leaderboard: `cognition.com/frontiercode` renders it via
JavaScript and returned "Loading leaderboard…" to my fetch, so **I could not
verify the competitive ranking against non-Cognition models.** Treat the
methodology as credible and well-documented; treat the ranking as unverified.

That said, the *direction* is corroborated by everything in §6 and §7 below.
Multiple independent lines of evidence say the same thing: **completion is not
acceptance.**

---

## 5. METR: the independent measurement, and why it is confusing

METR is the only organisation doing rigorous causal measurement here, and its
results have moved in both directions.

- **July 2025 RCT** ([primary](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/),
  [arXiv 2507.09089](https://arxiv.org/abs/2507.09089)): 16 experienced
  open-source developers, 246 tasks, mature repos they averaged 5 years on,
  using Cursor Pro with Claude 3.5/3.7 Sonnet. Result: **19% slower with AI**.
  Developers forecast a 24% speedup beforehand and reported a **20% speedup
  afterwards** — while having been measurably slowed down. The
  perception/reality gap is the durable finding, not the −19% itself.
- **Early 2026 follow-up**: METR now estimates roughly **+18% speedup** for
  experienced developers, then **announced a study redesign on 24 February 2026
  because selection effects from near-universal AI adoption made the new data
  hard to interpret** ([primary index](https://metr.org/research/)). Read that
  carefully: the honest measurement organisation says it can no longer cleanly
  measure this, because there is no unexposed control group left.
- **11 May 2026**: survey of 349 technical workers, **median 1.4–2× self-reported
  change in value of work** — self-reported, and the 2025 RCT is exactly the
  reason to distrust self-report (primary index).
- **8 May 2026**: research distinguishing **three different measures of AI
  uplift** and showing how task substitution makes them diverge (primary index).
  This is the most useful METR output for practitioners: "faster" is not one
  quantity.
- **10 April 2026 — MirrorCode**: agents completed **weeks-long coding tasks,
  including reimplementing a 16,000-line codebase** from behaviour alone
  (primary index; [paper](https://arxiv.org/pdf/2606.30182)). This is the
  strongest evidence *for* long-horizon capability that exists.
- **Time Horizon 1.1, 29 January 2026** ([primary](https://metr.org/blog/2026-1-29-time-horizon-1-1/)):
  the 50%-success task-length horizon doubling time **fell to ~89 days** since
  2024, versus ~7 months over 2019–2025. METR also published
  [limitations of the metric](https://metr.org/notes/2026-01-22-time-horizon-limitations/),
  and noted in May 2026 that **measurements above 16 hours are unreliable with
  the current task suite**.

**How to hold these together.** The capability trend is real and fast
(89-day doubling; 16,000-line reimplementation). The *realised productivity*
trend is small, contested, and swamped by measurement problems. The most
defensible reading: **agent capability is outrunning organisations' ability to
absorb it**, and the binding constraint has moved out of the model.

---

## 6. Where the constraint actually moved: review

This is the best-corroborated finding in the whole field, from four independent
source types.

**Vendor data.** Anthropic's 2026 Agentic Coding Trends Report: developers use
AI in roughly **60% of their work but can fully delegate only 0–20% of tasks**
*(vendor, [report](https://resources.anthropic.com/2026-agentic-coding-trends-report),
figures relayed via [Pathmode](https://pathmode.io/blog/orchestration-era-needs-intent))*.
A vendor with every incentive to claim otherwise is publishing a 0–20% delegation
ceiling.

**Delivery research.** DORA-lineage analysis: AI adoption improves throughput by
an estimated **2–18%** while **stability declines** — higher change-failure
rates *(secondary, [Augment](https://www.augmentcode.com/guides/software-delivery-performance-ai),
[Kodus](https://kodus.io/en/dora-accelerate-state-of-devops/))*. The 2024
analysis had throughput *negative* (−1.5% per +25% adoption) and stability
negative (−7.2%); by 2025 throughput turned positive and stability stayed
negative. The direction of travel is: **more code, less stable, and the delta
lands in the review queue.**

Concrete queue numbers, *(secondary — I could not trace these to the primary
DORA publication and they should be verified before being quoted externally)*:
**agentic PRs waited 5.3× longer for reviewer pickup (1,055 vs 201 minutes)**
and **AI-assisted PRs were 2.6× larger (408 vs 157 lines)**
([Larridin](https://larridin.com/blog/ai-code-review-bottleneck)).

**Practitioner research.** *"An Endless Stream of AI Slop"*
([primary, arXiv 2603.27249v3, 13 June 2026](https://arxiv.org/html/2603.27249v3)):
qualitative analysis of **1,154 Reddit and HN posts**, 978 coded, 1,603 codings
against a 15-code codebook. Findings: a **"tragedy of the commons" where
individual productivity gains externalise costs onto reviewers**; characteristic
AI failure modes named specifically — *setTimeout patches, unsafe type casting,
and tests manipulated to pass*; trust erosion because reviewers cannot tell
authorship and authors cannot explain their own submissions. One team reported
**30 pull requests per day across 6 reviewers**.

**The market's answer.** An automated-review industry now exists: **26% of
public-PR review comments come from an automated reviewer**; CodeRabbit is on
100,000+ repositories; Greptile claims 4,500 paying companies *(secondary,
[Greptile](https://www.greptile.com/content-library/best-ai-code-review-tools),
[Macroscope](https://macroscope.com/content/best-ai-code-review-tools-github-2026))*.

But the review tools **do not agree on their own efficacy**, and the
disagreement is instructive: Greptile reports catching 82% of bugs *in its own
July 2025 test*; Martian's independent 2026 benchmark put CodeRabbit top at
**51.2% F1**; Qodo's own February 2026 test put Qodo top at **60.1% F1**; Graphite
Diamond is very selective (0.62 comments/PR) and catches ~18% of bugs
*(secondary, [BirJob](https://www.birjob.com/blog/ai-code-review-tools-2026),
[particula](https://particula.tech/blog/greptile-vs-coderabbit-vs-qodo-ai-code-review-2026))*.
**Every vendor wins its own benchmark.** The consistent independent signal is
roughly 50–60% F1 — useful as a filter, nowhere near a replacement.

The community position was tested directly when a paper titled *"The End of Code
Review: Coding Agents Supersede Human Inspection"* hit Hacker News. The thread
rejected it near-unanimously, and the specific objections are worth recording:
the evidence amounted to agents detecting "the same categories of defect" with
"comparable" comments; knowledge transfer is not replaced by on-demand
summaries; and high PR volume often reflects bad decisions needing correction
rather than progress
([primary thread](https://news.ycombinator.com/item?id=48649183)).

---

## 7. Independent evaluation of the products themselves

Thin, and that is itself a finding.

- **Devin, Answer.AI, January 2025**: 20 real-world tasks → **3 successes, 14
  failures, 3 inconclusive** (~15%). Widely cited, and by August 2026 badly out
  of date — Devin has had a new model twice since. Secondary summaries claim
  community reports still cluster near 14–15% for complex autonomous tasks and
  **30–50% for well-defined tasks** *(secondary,
  [The AI Agent Index](https://theaiagentindex.com/agents/devin));
  I found no rigorous 2026 replication)*.
- **I found no independent, methodologically serious evaluation of any 2026
  factory product** — not Devin, not Factory Droids, not Superconductor, not
  Agent HQ. Everything current is vendor benchmark, aggregator listicle, or
  anecdote. **This is the largest evidence gap in the field.**
- The nearest thing to a real-world case study is StrongDM's radical experiment:
  five people, four repos on Kubernetes, rules of "code must not be written by
  humans / code must not be reviewed by humans," a technical preview shipped in
  ~15 working days — **delivered a week late**, with unanticipated inter-work
  dependencies, poor visibility into done-vs-remaining, cross-repo work falling
  out of process, and the conclusion that **five people was too many**
  ([secondary but first-hand](https://sigusr2.net/notes-on-not-looking-at-the-code.html),
  [factory.strongdm.ai](https://factory.strongdm.ai/)). Their fix was mundane:
  a structured ticket queue and a daily planning meeting.

---

## 8. Cost: what a task actually costs

Wide disagreement across sources, and the disagreement is real rather than
sloppy — it depends entirely on task size.

- Terminal-Bench 2.1 at max effort: **\$134–\$599 for 89 tasks ≈ \$1.50–\$6.70
  per task** *(primary, [leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1))*.
- Cognition Fusion published runs: **\$1.86–\$4.03 per run** on their eval
  *(vendor, [primary](https://cognition.com/blog/making-fable-cheaper-than-opus))*.
- Secondary aggregators quote anywhere from **\$0.03 to \$8 per task** depending
  on model and tool, and **\$150–\$250 per developer per month** on Claude Code,
  rising to **\$500–\$2,000/engineer/month** for heavy automation
  *(secondary, [morphllm](https://www.morphllm.com/ai-coding-costs),
  [kunalganglani](https://www.kunalganglani.com/blog/ai-agent-cost-per-task-2026))*.
- StrongDM's stated *target* was **\$1,000+ per engineer per day**
  *(secondary, [factory.strongdm.ai](https://factory.strongdm.ai/))*.

Two mechanisms explain the spread, and both are worth internalising:
**most of the bill is context overhead, not generated code**, and **a 10-turn
session costs closer to 50× a single call, not 10×**, because context is
re-sent every turn *(secondary, morphllm)*.

**The planning number to use:** **\$2–\$7 per non-trivial task attempt**, and
budget for **2–3 attempts per merged change** given the 42.3% mergeability
figure. So roughly **\$5–\$20 per merged PR** in model spend, plus sandbox time
that rounds to nothing.

---

## 9. What the evidence actually shows — the honest summary

1. **Capability is real, fast-moving, and better measured than adoption.**
   89-day time-horizon doubling; 16,000-line reimplementation; 83.8% on curated
   terminal tasks. These are not marketing.
2. **Completion ≠ acceptance.** The single best-designed mergeability benchmark
   puts the frontier at **42.3%**. Roughly half of "successful" agent work is
   not mergeable.
3. **The scaffold contributes ~7 points, and the harness market is priced as if
   it contributed 40.** mini-SWE-agent at 76.2% is the control experiment.
4. **The constraint has moved to review, and this is corroborated by vendor,
   academic, delivery-research and community sources independently** — the only
   claim in this document with four-way agreement.
5. **AI review tools are a filter, not a replacement:** ~50–60% F1
   independently, versus 82% self-reported.
6. **Product-level independent evaluation essentially does not exist for 2026
   factories.** Anyone buying one is buying on vendor benchmarks and vibes.
7. **Benchmarks themselves are contested**, with the field's reference benchmark
   abandoned by a frontier lab for contamination, and its most interesting
   successor owned by a competitor in the same market.

---

## 10. What a two-person agency does with this, in three months

1. **Benchmark on your own codebase; ignore the leaderboards for selection.**
   The top 7 entries are one statistical cluster. Take 20 closed PRs from a real
   client repo, replay them, and score mergeability yourself. That takes a week
   and beats every number in this file for your decisions.
2. **Adopt mergeability as your metric, not completion.** Copy FrontierCode's
   design: maintainer-defined criteria per task, some marked as **blockers** that
   cap the score. This is the cheapest high-value thing available and it is
   directly implementable — it is a checklist per ticket, not an ML system.
3. **Instrument two ratios and nothing else at first:** *human review minutes
   per merged PR* and *dollars per merged PR*. Everything in §6 says the first
   one is where your business dies; §8 says the second is where your margin
   dies. Target something like \$5–\$20 model spend per merged PR and
   **<15 minutes** of human review; if either blows out, the factory is not
   working regardless of how good the demos look.
4. **Cap PR size mechanically.** AI-assisted PRs run 2.6× larger and wait 5.3×
   longer for review. A hard line-count gate in the workflow is a one-hour build
   and directly attacks the measured failure mode.
5. **Add an automated reviewer, and treat it as a ~55% filter.** CodeRabbit at
   ~\$24/dev/month is the broadest platform coverage. It removes trivial review
   load. It does not remove you from the loop, and no independent benchmark
   suggests it will this year.
6. **Assume 2–3 attempts per merged change.** Design the queue for retries, not
   for one-shot success. Every capacity plan built on 80%-benchmark numbers will
   be wrong by roughly a factor of two.
7. **Write down what you cannot verify.** The field's biggest gap is
   independent product evaluation. An agency that publishes honest, dated,
   reproducible measurements of its own factory has something almost nobody in
   this market has.
