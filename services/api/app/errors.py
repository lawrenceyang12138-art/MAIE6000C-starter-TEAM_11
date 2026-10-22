"""Shared HTTP error body for every route in the application API.

Contract 6.1 fixes one shape: a lowercase snake_case ``code`` plus a display
``message``. D maps ``code`` to its own copy, so the code is the contract and
the message is only a fallback for logs and unmapped cases.

Contract 6.2 adds one requirement on top: a scan conflict must carry the
existing ``root_id`` and ``job_id`` so a client whose first request timed out
can recover without guessing. Those travel as extra keys in the same envelope
rather than as a second body shape.
"""

from __future__ import annotations

from typing import Any


def reason(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build one error body, keeping the two contract keys first.

    ``extra`` entries with a ``None`` value are dropped: a null identifier reads
    as "there is one, but we could not resolve it", which is worse than absent.
    """
    body: dict[str, Any] = {"code": code, "message": message}
    body.update({key: value for key, value in extra.items() if value is not None})
    return body
