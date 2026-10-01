# First completed run

Issue [#14](https://github.com/tekncoach/liberty-rider-myroadtrips/issues/14) → draft PR [#15](https://github.com/tekncoach/liberty-rider-myroadtrips/pull/15), run `fadedace`, 145 events, $1.02 on `claude-sonnet-5`.

| | |
|---|---|
| Read the ticket | `fetch_ticket` |
| Located the patterns it named | `bash`, `str_replace_based_edit_tool` |
| Wrote the endpoint | 73 lines in `app.py`, following `RIDE_LIST_COLS`, `_merged_ride_dict` and `_merge_members_map` as the ticket asked |
| Wrote the tests | six, in `tests/test_stats.py` |
| Ran them | 5 passed, **1 failed**: `test_stats_counts_merged_ride_once` |
| Fixed its own failure | the merged-ride double-count rule |
| Verified independently, afterwards | **181 passed, 0 failed** |

The docstring it wrote for the endpoint explains the rule rather than restating the code:

> a merged ride's numbers already live on the ride that absorbed it, so counting both would double every merge

It did **not** open the PR itself: the anti-spin guard stopped it one call short, because `run_tests` with identical arguments looked like a repeat when it was the edit-test loop doing its job. That guard now lets a tool declare itself repeatable, and the PR was opened from the work already on disk.

It took eight attempts to get there, and six of the eight blockers were this project's own guards, not the model. They are listed in [`COST-AND-LIMITS.md`](COST-AND-LIMITS.md#known-limits).
