# agent/consent.py
#
# Which ticket this run is authorised to work, for the length of the run.
#
# The agent:ready contract was checked in two places — the service door, and
# inside open_pr before it proposes. Neither is where the first write happens.
# str_replace_based_edit_tool had no idea which ticket it was serving, so an
# issue nobody labelled could have code written for it; only the proposal was
# refused, and by then the working tree was already changed. F24.
#
# A ContextVar rather than a module global: one process serves concurrent
# requests, and a global would leak one request's authorisation into another's
# write. That is the failure this file exists to prevent, not a smaller one.
from __future__ import annotations

from contextvars import ContextVar

_authorised: ContextVar[int | None] = ContextVar("authorised_issue", default=None)


def authorise(issue_id: int | None) -> None:
    """Record that this run may work that issue. Called once, at the door,
    only after check_ready has said yes."""
    _authorised.set(issue_id)


def authorised_issue() -> int | None:
    return _authorised.get()


def clear() -> None:
    _authorised.set(None)
