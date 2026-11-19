"""Add cooperative leases to jobs.

A claimed job now records who holds it and until when. An expired lease makes
the row claimable again, so a worker that dies mid-job stops stranding work.
Both columns are nullable: pending and terminal rows keep them empty, and
downgrading drops them without touching job history.

Revision ID: 20261119_0006
Revises: 20261030_0005
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261119_0006"
down_revision: str | None = "20261030_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("lease_owner", sa.String(length=80), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "lease_owner")
