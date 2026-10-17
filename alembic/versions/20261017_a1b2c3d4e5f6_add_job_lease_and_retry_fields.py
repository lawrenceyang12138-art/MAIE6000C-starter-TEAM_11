"""add job availability, lease and worker identity

Revision ID: a1b2c3d4e5f6
Revises: 7f3a1b2c4d5e
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7f3a1b2c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("worker_id", sa.String(length=120)))
    op.execute("UPDATE jobs SET available_at = created_at")
    op.create_index("ix_jobs_available_at", "jobs", ["available_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_available_at", table_name="jobs")
    op.drop_column("jobs", "worker_id")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "available_at")
