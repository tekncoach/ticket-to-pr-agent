# Risk memo: the ticket-to-pull-request agent

For the person deciding whether this agent may touch a repository. It says what the agent does, what leaves your environment, who stays in control, what is recorded, and what can go wrong. Where something is not built, it says so.

## What it does, and what it does not do
A person on your team labels an issue `agent:ready`. The agent reads the issue, looks at the repository, edits a working copy, runs the repository's tests, and opens a **draft** pull request with a comment on the issue.

It has no tool that merges, approves, deletes a branch, or touches a repository other than the one it is configured for. It does not act on an unlabelled issue, and it refuses to edit a file for an issue it has not been authorised to work.

## Data handling
| What | Where it goes |
|---|---|
| The issue text and any file the agent reads or edits | to the model provider (Anthropic's API), as part of the conversation |
| The text of the agent's knowledge-base searches, derived from the issue | to HuggingFace's inference API, to be turned into a vector |
| Pull requests, branches and comments | to your GitHub repository, through one access token limited to that repository |

**What is scrubbed.** Issue titles and bodies are scanned for secret-shaped strings (access tokens, API keys) before the model sees them or they are logged. So are the responses and errors GitHub sends back.

**What is not.** Repository files the agent reads are **not** scanned. A secret committed inside a source file would reach the model and the log. Text the agent writes into a pull request or a comment is not scanned on its way out either. The file editor refuses a short list of path names configured per target (two in the reference setup, `crypto.py` and `migrations`); the shell is confined to the checkout and has no such list. Neither is a scan for secrets.

**The access token** is a fine-grained token limited to one repository, with write access to issues, pull requests and contents. The scopes are enough, technically, to merge a pull request, which is why the condition below on branch protection matters.

## Who stays in control
- **Every change is a draft pull request** that a person must open, read and merge. The agent cannot merge.
- **A kill switch** stops the agent, or stops writes while letting it keep running, or disables one tool. Each is a single environment variable. `GET /health` reports their state. The current procedure needs SSH access to the host, held by one person.
- **By default nothing is written**: a deployment that has not explicitly turned writes on produces receipts and changes nothing.

## What is recorded, and for how long
Each run writes one log file: the system prompt, every tool call with its arguments and result, token counts and timings. That includes the repository code the agent read. A run can be replayed from it with no model call.

**Retention is not implemented.** Nothing deletes these files. They stay on the host until someone removes them. We recommend a limit, which you choose (30 days is a common starting point), and we will build the deletion once you have chosen it.

## What can go wrong
Measured on 35 replayed tickets from an open-source project, not on your repository:
- **Most runs do not produce a usable change.** About a third reach a proposal, and 11–14% are usable as written.
- **Some changes look right and are wrong.** In one case the agent changed a core property that every outgoing request depends on; merged, it would have dropped the query string from real traffic. Nothing automated flagged it as a problem in production terms; a person reading the diff would.
- **Some runs write outside what was asked.** 4 of 35 edited a file the engineer had not touched.

For these reasons the plan reads every pull request through the first three stages and starts with a narrow slice of small, one-file changes: [`SHADOW_ROLLOUT.md`](SHADOW_ROLLOUT.md).

## What we ask you to set up
1. **Branch protection** on the target branch requiring a person's review, so a pull request cannot merge itself.
2. **A named owner**, and a **second person** with access to the kill switches.
3. **A retention period** for the run logs.
4. **A daily spend limit** with the model provider. A typical attempt costs about three cents; the limit is yours.
5. **A decision on repository secrets**: the agent should not be pointed at a repository that commits secrets in source files.

## Status
Shadow only for any deployment. The only real writes so far went to the reference repository this project was built against: one draft pull request and some issue comments. The plan does not move to a stage that writes until a second sample supports it.
