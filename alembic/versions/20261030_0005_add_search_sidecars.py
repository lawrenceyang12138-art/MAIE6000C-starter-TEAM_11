"""Add C-owned token and physical-page search sidecars.

Both tables are derived from canonical source chunks/versions. They are
additive, cascade with their source rows, and never alter file text or the
legacy dense vector column.

Revision ID: 20261030_0005
Revises: 20261029_0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261030_0005"
down_revision: str | None = "20261029_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_token_search_index",
        sa.Column(
            "chunk_id",
            sa.String(length=36),
            sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("model_revision", sa.String(length=64), nullable=False),
        sa.Column("token_dimensions", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "token_vectors",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_table(
        "version_page_search_metadata",
        sa.Column(
            "version_id",
            sa.String(length=36),
            sa.ForeignKey("file_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("parser_revision", sa.String(length=50), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_count > 0",
            name="ck_version_page_count_positive",
        ),
        sa.CheckConstraint(
            "byte_size >= 0",
            name="ck_version_page_byte_size_nonnegative",
        ),
    )


def downgrade() -> None:
    op.drop_table("version_page_search_metadata")
    op.drop_table("chunk_token_search_index")
