# GitHub Token

`GITHUB_TOKEN` in `.env` (never committed) — a fine-grained personal access token, resource owner `tekncoach`, repository access limited to `liberty-rider-myroadtrips` only. Used by every tool that calls the GitHub REST API.

## Scopes set, and what actually uses them

| Scope | Level | Used by |
|---|---|---|
| Issues | Read and write | `fetch_ticket` (read, built) · `comment_on_ticket` (write, planned) |
| Pull requests | Read and write | `open_pr` (planned) |
| Contents | Read and write | `open_pr` — pushes a branch (planned) |
| Actions | Read-only | `get_ci_status` (planned) |
| Metadata | Read-only | Automatic on every fine-grained token — cannot be unchecked |
| Code quality, Discussions, Merge queues, Secret scanning alerts, Code scanning alerts, Dependabot alerts | Various | Not used by any tool in this repo. Left over from the GitHub UI's suggested defaults at creation time — harmless (nothing here calls those endpoints) but broader than needed. |

## Regenerating it

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.

- Resource owner: `tekncoach`
- Repository access: only `liberty-rider-myroadtrips`
- Permissions: the scopes in the table above

Paste the value straight into `.env` with a text editor — never through a shell command that would echo it into a terminal session or a chat log.
