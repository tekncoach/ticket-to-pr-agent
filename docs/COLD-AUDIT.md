# The cold audit

A reviewer who has never seen this code finds defects its author cannot. That
is not a difference in care or in capability — it is that the author reads the
intent and the reviewer reads the code.

Run before any submission, release, or day's close:

```
make audit    # prints the brief; paste it to a fresh reviewer with no context
```

## Why it exists

Ten defects were found in one pass, seven of them in code written that week,
two of them exploitable. Every one had been read three times by the person who
wrote it. The most serious — a write gate that checked the label only when a
ticket had been authorised, and skipped the check entirely when none had — was
*reasoned into existence* and then reread as correct, because the reasoning was
still in the reader's head.

## The seven lenses

They are not generic review advice. Each one is a defect class this repository
has actually shipped, and the auditor is told to look for more of that exact
shape.

1. **A guard that cannot fire.** A detector matching a string the code never
   emits; a threshold compared against a metric that is always `None`. Grep the
   matcher, grep what produces the value, compare them. Four found this way.
2. **A number that cannot be computed, reported as a value.** A guarded
   denominator returning `0.0` where the truth is "not measured".
3. **A comment that claims what the code does not do.** Dense assertive
   comments age into lies; each load-bearing one is checked against the lines
   beneath it.
4. **State that leaks or is lost.** Module globals where concurrency exists;
   serialisation dropping a field its consumer reads.
5. **A test that passes for the wrong reason.** One whose assertion would hold
   with the feature deleted; a fixture making it trivially true.
6. **Off-by-one and boundary.** Ranking, percentiles, slicing, retry counts.
7. **Error paths that swallow.** A bare `except` hiding a real failure; a
   fallback returning a plausible wrong answer.

## The rules that make it worth reading

**Every finding is proved or dropped.** `file:line`, the code quoted, what it
should do, and one command or assertion that demonstrates it. An empty finding
list is an acceptable answer; a padded one is not.

**No formatting, naming, or "consider adding".**

**And every finding is run against the code before it is fixed.** One of the
ten was a real mechanism with the wrong conclusion — cycle-0 posting on a
failed read is a considered trade, not a bug, and the test beside it says so.
It is recorded as accepted rather than fixed. Correcting the reviewer with a
measurement is worth more than agreeing with it.
