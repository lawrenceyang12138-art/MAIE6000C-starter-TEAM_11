"""Recover jobs that were claimed before leases existed.

Migration 0006 added ``lease_owner`` / ``lease_expires_at`` as nullable, so a row
that a pre-lease worker left ``claimed`` has no deadline and the new claim
predicate can never select it: it is neither pending nor claimed-with-an-expired
lease. This revision gives those rows an already-expired deadline, which is what
returns them to the queue on the next poll.

Drain or stop the old worker before upgrading. On a mixed-version rollout the
new worker would reclaim a job the old one is still executing; the lease cannot
protect a process that does not renew it.

Downgrade is a no-op: the deadline cannot be told apart from a real lease after
the fact, and clearing it would strand the rows again.

Revision ID: 20261119_0007
Revises: 20261119_0006
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20261119_0007"
down_revision: str | None = "20261119_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE jobs SET lease_expires_at = now() "
        "WHERE status = 'claimed' AND lease_expires_at IS NULL"
    )


def downgrade() -> None:
    # Data-only recovery; there is nothing to undo that would not strand rows.
    pass
