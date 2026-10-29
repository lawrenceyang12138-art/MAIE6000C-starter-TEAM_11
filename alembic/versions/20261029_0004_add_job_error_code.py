"""Add a stable failure reason to jobs.

One additive, nullable column. Until now the public ``error_code`` could only say
``job_failed``, because the diagnostic text in ``jobs.error`` is not exposed. The
new column carries the reason the handler recorded (``file_missing``,
``source_changed``, ...), which is what tells a retryable failure apart from an
internal one.

Revision ID: 20261029_0004
Revises: 20261029_0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261029_0004"
down_revision: str | None = "20261029_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_code", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_code")
