# The AI-Native SDLC Playbook

Source: https://claude.com/blog/the-ai-native-sdlc-playbook (Anthropic).
This file is a structured synthesis of that article, not its verbatim text.

## Core thesis

Code is no longer the bottleneck. The traditional SDLC was designed when
writing code was the constraint; organisations must rebuild their processes
around what agentic AI enables while keeping human oversight above the loop.

Six stages: Plan, Design, Build, Test, Deploy, Maintain.

## Stage 1 — Plan: capture as intent.md

Ideas become version-controlled `intent.md` files produced by brainstorming
with Claude rather than multi-week requirement cycles. Contributors describe
problems in their own words; Claude asks clarifying questions and synthesises
findings into a document that is both human readable and machine actionable.

## Stage 2 — Design: requirements and design collapse into one session

Claude takes the approved `intent.md` and produces requirements and design
specs guided by organisational skills — brand, security, compliance, UX
standards. Policy is applied while the spec is written, not discovered in a
review weeks later.

## Stage 3 — Build: plan mode and CLAUDE.md

Plan mode reads the codebase without changing it; Claude interviews the
engineer about implementation strategy and commits a `plan.md` before any code
is written, which prevents design rework after coding begins.

Institutional knowledge lives in `CLAUDE.md` — conventions, architecture,
common mistakes — kept current and team-maintained. Skills encode policies as
reusable instructions. Hooks act as build-time guardrails: protecting paths,
running formatters. Parallel sessions let one engineer run several independent
workstreams.

## Stage 4 — Test: feedback loops and evals

Sessions verify their own work before a human reviews them. Developers define
quantifiable targets and Claude iterates until the checks pass. Continuous
evals in CI regression-test the configuration that steers the agents whenever
`CLAUDE.md`, skills or hooks change — the configuration is tested like code.

## Stage 5 — Deploy: review and approval gates

Claude participates in code review with policy-based findings while humans
assess intent and risk. Review comments tagged `@claude` trigger automated
fixes. Hooks enforce approval gates for production changes. CI/CD runs Claude
non-interactively for judgment steps such as triaging failures. Human review
is reserved for regulated and critical code.

## Stage 6 — Maintain: closing the loop

Autonomous triggers — a breached control band, an incident, a ticket — invoke
Claude without a human starting it. Detection scripts use deterministic rules;
Claude diagnoses at lower tiers and proposes fixes at higher ones. Findings
become a new `intent.md`, which restarts the pipeline.

## Governance and audit

Every stage commits a versioned artifact: intent.md, spec.md, plan.md, code,
review findings. Git history is the audit trail, with authorship and
timestamps. Permissions, hooks and managed settings enforce controls
deterministically. Approval gates preserve separation of duties — an agent
cannot approve its own work.

## Metrics

Leading indicators: time from idea to committed intent.md; elapsed time
between intent and spec commits; share of changes merging from the first
implementation pass; first-pass CI success rate.

Lagging indicators: survival rate of intent.md through to production;
requirements rework after build starts; defects and vulnerabilities reaching
production; repeat incidents by class.

## The shift, stage by stage

| Stage | Traditional | AI-native |
|---|---|---|
| Plan | multi-week elicitation | hours to intent.md |
| Design | separate analyst and designer phases | one prompted session with skills |
| Build | handwritten code, knowledge in heads | agent-generated with CLAUDE.md and skills |
| Test | QA gates at boundaries | continuous evals woven through |
| Deploy | manual review of every line | layered agentic review plus human judgment on intent |
| Maintain | reactive incident response | autonomous monitoring and loop closure |

## The principle

The loop keeps running. Human judgement stays above it.
