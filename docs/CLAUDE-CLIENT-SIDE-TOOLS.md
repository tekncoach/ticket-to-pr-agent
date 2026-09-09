# Anthropic Client-Side Tools

Reference for Claude's Anthropic-defined tool types that Claude never executes — your own code runs them. Distinct from *server-side* tools (`web_search`, `web_fetch`, `code_execution`, `tool_search`, `advisor`), which Anthropic actually runs on its own infrastructure.

## The three tools

| Tool | `type` | `name` | What it does |
|---|---|---|---|
| Bash | `bash_20250124` | `"bash"` | Runs a shell command — you execute it, typically via `subprocess` |
| Text Editor | `text_editor_20250728` | `"str_replace_based_edit_tool"` | View/create/edit a file (str-replace based) — you read/write the file |
| Memory | `memory_20250818` | `"memory"` | Read/write files in a directory that persists across sessions — you manage that directory |

All three are **schema-less**: declare them by `type` + `name` only, never pass `input_schema` — Claude already knows each tool's input shape, and supplying one is rejected.

No native `read_file` or `grep_repo` exists. `grep`, `cat`, `find`, `ls` are plain shell commands with no dedicated Anthropic type — reach for `bash`.

## Bash: input shape and security

`tool_use.input` is either `{"command": "<string>"}` or `{"restart": true}` — check `restart` first (reset the session, return a confirmation string), then run `command` and return combined stdout + stderr.

Anthropic's own security guidance: **an allowlist, not a blocklist.** Commands are untrusted model output — run them in a restricted environment, allowlist permitted executables, reject shell operators (`&&`, `|`, `;`, backticks, `$()`), set timeouts, log every command.

See `tools/bash.py` in this repo for a worked implementation: an executable allowlist, `shell=False` throughout, and a hand-built `subprocess.Popen` pipeline so a plain `|` between two allowed read-only commands still works — the danger is `shell=True`, not the pipe character itself.

## Text Editor: commands

| `command` | Other inputs | Action |
|---|---|---|
| `view` | `path`, optional `view_range` | Return file contents or directory listing |
| `create` | `path`, `file_text` | Create/overwrite file; back up if it already exists |
| `str_replace` | `path`, `old_str`, `new_str` | Replace exactly one occurrence; error if 0 or more than 1 match |
| `insert` | `path`, `insert_line`, `insert_text` | Insert text after line `insert_line` (0 = start of file) |

Security: `path` is untrusted model output. Resolve it to canonical form and verify it stays inside the project root before touching the filesystem — never call `open()` / `write()` on the raw value.

## Verify this list yourself

This is a living API surface — check before trusting this file if it's more than a few months old:

- https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview.md
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/bash-tool.md
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool.md
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool.md

## Used in this repo

`bash_20250124` replaced a hand-rolled `read_file` / `grep_repo` pair — see `docs/SPEC.md` (Tools section) for why, and the guardrails built around it. `edit_file` stays hand-rolled for now; `text_editor_20250728` is named there as its natural next swap.
