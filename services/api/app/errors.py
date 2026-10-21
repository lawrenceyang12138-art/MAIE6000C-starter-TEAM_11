"""Shared HTTP error body for every route in the application API.

Contract 6.1 fixes one shape: a lowercase snake_case ``code`` plus a display
``message``. D maps ``code`` to its own copy, so the code is the contract and
the message is only a fallback for logs and unmapped cases.

This lived inside ``parsing_routes`` first; it is shared now so the mount, root
and job routes answer in the same envelope instead of adding a third copy.
"""

from __future__ import annotations


def reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}
