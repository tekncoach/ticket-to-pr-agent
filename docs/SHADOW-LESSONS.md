# Shadow mode: what went wrong, and what it changed

The shadow runner ([`shadow/`](../shadow/README.md)) was built over several batches, and each one exposed a defect in the harness before it said anything about the agent. Results are in [`shadow/ANALYSIS.md`](../shadow/ANALYSIS.md). This file keeps the defects, because each one is a rule for the next measurement. Ids refer to [`evals/failure-modes.csv`](../evals/failure-modes.csv).

## A gate says no, shadow says done (F40)

The first version closed the runtime's write gate. The gate answers DENIED, so the agent tried to edit, was refused, retried, and stopped without ever stating what it would have changed. Write tools are now replaced by no-ops that return the full payload they would have sent. The agent believes it succeeded and carries on, which is the behaviour being observed.

## The guardrail has to read `stopped_on` (F41)

The completion rate first checked for an empty answer. The runtime's stop sentence lives in that field, so three runs killed by a guard were counted as finished and completion read 1.0 instead of 0.0. A run with `stopped_on` set did not reach a proposal, whatever its answer holds.

## The prompt must name the workspace (F42)

The shadow prompt said "you are inside a checkout" without the path, so the agent guessed `/repo/...` and the workspace guard refused it, on all three units of the first batch. `agent/tickets.py::task_prompt` had named the path since Day 4; the shadow prompt was written separately. Naming it moved completion from 0.0 to 0.333 on the same three units, with no other change.

## Run each unit at its own base commit (F45)

The first fifteen units ran against current `main` while the traffic is historical, so the agent was asked for changes already present in the files it read. On `#2715` it said so, correctly (`socket_options` "IS already implemented"), and the comparator scored it as half a hit for touching the right file. `base_sha` had been in every traffic record since the first harvest and was never used.

`checkout_base()` now sets the tree to the pull request's parent commit before each unit. A unit that cannot get there carries `tree_error` and gets the `wrong-tree` verdict instead of a score.

## Redact values, not the serialised document

The first version redacted the JSON text, and the phone pattern ate the punctuation between fields, producing records that would not parse. `redact_deep` walks the strings inside the structure.

## A small sample does not support a claim (F43, F44, F46, F47)

After three units, two failure modes were called structural: the agent improvising a shell to write (F43), and `run_tests` failing on a clone with no virtualenv (F44). Fifteen units on correct trees said otherwise:

- F44 was not seen once.
- F43 was real and small: 2 units, 5 refusals.
- F46 was new and larger: 4 units stopped reaching for `xargs`, `echo` or `python3`, which are read-side commands on a codebase the agent has to discover.
- F47 was new: 4 of 11 incomplete runs hit no guard at all.

Guards were involved in 7 of the 11 incomplete runs, which supports the umbrella finding F39 and not the two specific modes named under it.

## The comparator corrects a read by eye

Read by eye, the first batch looked like two hits out of three. The comparator said one, and was right. That is the reason the comparison is computed, and not summarised from the logs.

## Cost, and why the batch stopped at 35

Measured from the runs' token counts: about $0.03 a unit on `claude-haiku-4-5`, $1.14 for the 35 recorded units. The full corpus is 60 units: `make shadow-run LIMIT=60 SKIP_DONE=1` runs the 25 left, for about $0.80. The batch stopped at 35 because it already held 30 disagreements, twice the 15 the readout reads, and to cap spend. Each slice is priced before the next is run (`SKIP_DONE=1` adds to the batch instead of replacing it).
