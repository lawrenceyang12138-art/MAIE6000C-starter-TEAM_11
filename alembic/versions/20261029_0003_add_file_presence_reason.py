"""Add a reason for a file the scan could not read.

One additive, nullable column. ``presence_status`` already says *that* a file is
missing or unavailable; this column says what the scanner actually hit, so the
file list can explain itself instead of the file silently dropping out.

Revision ID: 20261029_0003
Revises: 20261015_0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_0003"
down_revision: str | None = "20261015_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "files", sa.Column("presence_reason", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("files", "presence_reason")
