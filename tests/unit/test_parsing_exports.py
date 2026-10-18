"""The package-level API must name things it actually exports."""

from __future__ import annotations

import services.parsing as parsing


def test_every_public_export_resolves():
    missing = [name for name in parsing.__all__ if not hasattr(parsing, name)]

    assert missing == []
