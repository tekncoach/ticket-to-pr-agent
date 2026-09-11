# SDLC with tools

Two audiences for this one diagram: what the Day 3 sprint POC actually builds (a subset), and the reference shape for the fuller production pipeline this project is heading toward over the next few days. Legend:

- ✅ built
- ❌ decided, not yet built (this sprint's remaining scope)
- 🔮 reference for the future production pipeline — **not** part of this sprint's tool count; see the note below the diagram

```
 1. INTAKE            fetch_ticket(issue_id)                    ✅ built
    read the ticket → title + body as the spec
          │
          ▼
 2. ORIENT            bash (read-only: grep/find/cat/ls/...)    ✅ built
    explore the codebase, locate what needs to change
          │
          ▼
 3. PLAN              (in-context reasoning — no tool)
    decide the approach: which files, what change
          │
          ▼
     ┌──────────────────────────────────────┐
     │ 4. IMPLEMENT    edit_file              │◄─────────┐  loop while
     │    edit the code, one edit at a time   │          │  anything below
     └────────────────┬───────────────────────┘          │  is red
                       ▼                                  │  (bounded by
     ┌──────────────────────────────────────┐            │  MAX_TURNS)
     │ 5. LINT / FORMAT   lint_check       🔮 │            │
     │    (production-pipeline reference)     │            │
     │    → returns a short summary only      │            │
     └────────────────┬───────────────────────┘            │
                       ▼                                    │
     ┌──────────────────────────────────────┐              │
     │ 6. TYPE CHECK      type_check       🔮 │              │
     │    (production-pipeline reference)     │              │
     │    → returns a short summary only      │              │
     └────────────────┬───────────────────────┘              │
                       ▼                                      │
     ┌──────────────────────────────────────┐                │
     │ 7. TEST            run_tests           │────────────────┘
     │    run the suite locally               │
     │    → returns a short summary only      │
     └────────────────┬───────────────────────┘
                       │ all green
                       ▼
 8. COMMIT           git_commit(files, message)                ❌ to build
    git add + commit locally — a distinct tool from push, so
    the agent can make atomic or partial commits
          │
          ▼
 9. PUSH             git_push(branch)                          ❌ to build
    push the branch to origin
          │
          ▼
10. OPEN PR          open_pr(branch, title, description)       ❌ to build
    GitHub API call — creates the PR, draft (shadow mode)
          │
          ▼
11. WAIT FOR CI      get_ci_status(pr_id)                       ❌ to build
    internal poll (GitHub Actions API) until terminal or timeout
          │
          ▼
12. REPORT           comment_on_ticket(issue_id, status)        ❌ to build
    post the outcome back on the issue
```

## Notes

**Lint/type-check are reference-only for this sprint, on purpose.** `docs/SPEC.md`'s Control points section already made this call: *"Lint, type-check, and coverage stay CI-only for now... we do not pre-add controls whose need we have not measured."* They're drawn here because the production pipeline this project is heading toward will want them as local gates — not because the Day 3 POC agent runs them today.

**Steps 5, 6, 7 (lint, type-check, test) return a summary only — never raw tool output into the agent's context.** A full `pytest` run or a linter pass over dozens of files can be thousands of tokens of noise; none of it is decision-relevant to the model beyond "did it pass, and if not, what and where." Each of these tools' `ToolResult.data` should be a condensed result — pass/fail counts, the list of failing test names, a short error snippet per failure — not the raw stdout dump. This is a contract for whoever builds `run_tests` (this sprint) and `lint_check` / `type_check` (production pipeline): summarize inside the tool, before it ever reaches the model.

**`git_commit_and_push` was one tool in the original SPEC; split into `git_commit` + `git_push` here.** One mega-tool bundling two different capabilities (local git state vs. pushing to a remote) hides two failure points behind one call, and blocks atomic/partial commits — the same "no bundled side effects" lesson the Day 3 tool-design feedback already flagged once.

**Git vs. `gh` CLI.** `git_commit`/`git_push` run plain `git` via subprocess — there's no GitHub API involved in a local commit or a push, so this isn't a hand-rolled-vs-CLI question at all. The real question is for the GitHub-API-facing tools (`open_pr`, `get_ci_status`, `comment_on_ticket`): hand-written `httpx` calls (current pattern, already proven in `fetch_ticket`) vs. shelling out to `gh`. [`docs/research/spec.md`](research/spec.md) already names `gh` as the *later* swap-in, not the POC default — staying with hand-written calls also means reusing `fetch_ticket`'s already-working Tool/ToolResult shape instead of building a second, different execution pattern (subprocess + text/JSON parsing of `gh`'s output) this sprint.

**Not automated: CI-red-after-local-green.** If CI fails after local `run_tests` passed, v1 does not loop back into more edits — it reports via `comment_on_ticket` and stops. `SPEC.md`'s own north-star metric names that gap explicitly (env divergence between local and CI) as Day 7-9 territory, not something this sprint's loop repairs.
