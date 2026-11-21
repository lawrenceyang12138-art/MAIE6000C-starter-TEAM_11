"""Attempt ownership shared by the worker and the handlers it calls."""

from __future__ import annotations


class StaleClaim(RuntimeError):
    """The job moved to another attempt; this worker must not publish."""


def is_owned(attempts_on_row: int | None, claim_attempts: int) -> bool:
    return attempts_on_row is not None and attempts_on_row == claim_attempts
