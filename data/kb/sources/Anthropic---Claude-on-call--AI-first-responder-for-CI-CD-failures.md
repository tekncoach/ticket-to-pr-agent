# Claude on call: an AI first responder for CI/CD failures

Source: https://claude.com/blog/ai-ci-cd-on-call (Anthropic).
This file is a structured synthesis of that article, not its verbatim text.
An engineer on Anthropic's Continuous Integration team describes the agent
that powers CI incident response at the company.

## What it does

Claude Tag has been the on-call first responder for CI/CD failures at
Anthropic for several months. It publishes its first analysis typically within
15 minutes; the median first evidence-grounded analysis lands 14 minutes after
an incident opens, and in the fastest cases it names the root cause within 4.

A worked example: roughly 44 tests on a new service stopped firing at 10pm.
Claude identified that they disappeared when a feature flag was activated that
morning, confirmed a revert was safe, and after the revert pinged back three
minutes later to verify the skip rules were gone and the error rate had
returned to baseline.

## The setup

Four things are needed: memory, connections and access, schedules, and
instructions.

Claude Tag is the backbone, holding memory across the on-call Slack channel
and providing per-turn instructions during incidents. It acts in real time on
events in relevant channels and manages scheduled routines from natural
language — "run CI handoff every Monday at 9:00am EST".

The service account has the tools CI engineers need (Datadog, Grafana), set up
by an administrator, and monitors other channels for context: service alerts,
configuration changes, PR updates.

Standing instructions live as markdown files in a GitHub repository so several
teammates can iterate on them and changes are managed like code. They carry
routing instructions, policies, and a lessons-learned log that supports
self-improvement.

## Detection

Two failure modes preceded this: humans cannot set perfect alert rules with
perfect thresholds, and alert fatigue follows from having to vet every alert.

Claude analyses data from a new service over its first few days to suggest
additional rules and tune thresholds that are too broad or too narrow. It then
applies criteria to every alert to decide whether to page or to document —
for example: "if the error rate exceeds 2% for longer than 5 minutes AND it is
not a known deploy window, page the on-call; otherwise write it to lessons.md".

Alerting is deterministic; escalation has both deterministic and agentic paths.

## Triage

An orchestration agent spins up executor subagents to investigate each
dependency and information source — Grafana, log storage, PagerDuty, GitHub,
Kubernetes, Slack incident channels, all via MCP connectors. Leads are pursued
in parallel, which reduces MTTR. Executors report back to the orchestrator,
which synthesises a coherent situation report.

Both follow an investigation skill with reference markdown per bug class — one
is 617 lines, for shadow divergence bugs, encoding the typical troubleshooting
steps. These skills were built by troubleshooting with Claude during real
incidents and then having it write the file from that experience.

`lessons.md` is a running log of every resolved incident: what happened, root
cause, fix, memorable gotchas. Claude appends to it automatically, so each new
investigation starts by reading recent ones. When a pattern repeats often
enough it is promoted into the investigation skill itself.

## Resolution

Most deployments sit behind feature flags. A separate agent in Claude Code,
with the right permissions, handles progressive deployment behind them: the
first rollout stage has Claude managing canary traffic, watching for issues,
and ramping up or down automatically.

Other resolution paths: deciding whether a Kubernetes section needs draining
or cordoning, giving instructions for scaling during demand surges, and
opening pull requests for review and merge.

## Verification, communication and handoff

Claude verifies its own fixes with the same connectors it investigated with,
then writes post-mortems to `lessons.md` and a handoff situation report,
following standing instructions in `oncall.md`.

A separate `ci-weather` agent compiles each incident channel, build metrics,
merge queue stats and deploy lag into a newsroom-style report on a public
channel, so engineers read the channel rather than pinging the team. The
format took several iterations: Claude can generate a status report in one
attempt, but readability depends on a team's own communication style.

## Why it exists

Engineers at Anthropic ship roughly 8x as much code per quarter as in
2021-2025, while every PR keeps a named owner, changes require approval, and
every change goes through CI gates. Keeping up with agentic coding requires
agentic CI.

Claude takes the tedious parts — after-hours disruption, incident
communication — so engineers work on the architectural changes that improve
reliability over the medium and long term.
