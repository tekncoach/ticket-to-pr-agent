# shadow/baseline.py
#
# The shape of the half of a pairwise record that is not ours.
#
# This began as a class in agent/shadow.py, the Day 10 starter template, and sat
# there unused: harvest.py built the same five keys as a hand-written dict, so the
# class documented a contract that nothing enforced, and the template's own
# stubs around it (names it never imported, a record built with `...`) would have
# raised if anyone had called them. It lives here now and harvest.py builds every
# baseline through it.
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Baseline:
    """What the current system actually did, for the same input.

    The half of a pairwise record that is not ours, and the one the whole day
    turns on: without it a shadow run is just a run.

    `source` says where the answer came from, and it is load-bearing rather than
    descriptive. A baseline taken from our own agent on an earlier revision is a
    different claim from one a human wrote, and reading a number without knowing
    which is how a comparison flatters itself.

    `action` is what was done in one line. `artifact` is the evidence, a diff, a
    comment body or a URL, so a disagreement can be read rather than trusted.
    `files` are the paths the change touched: comparing "1 file" to "1 file" says
    nothing, comparing which file says whether the agent found the same place.
    `at` is when, because a baseline drifts.
    """

    source: str  # "merged-pull-request" | "human-comment" | "agent-revision:<sha>" | "none"
    action: str
    artifact: str | None = None
    at: str | None = None
    files: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(cls, why: str) -> Baseline:
        """No baseline for this input, said out loud.

        Not an empty dict: a record whose baseline is silently blank reads as
        agreement with nothing, and averages into the comparison as though it were
        a measurement. Same rule as the eval metrics: a value that could not be
        computed is named, never defaulted. shadow/diff.py reads source "none" as
        the baseline-unavailable verdict.
        """
        return cls(source="none", action=why)

    def as_record(self) -> dict:
        return asdict(self)
