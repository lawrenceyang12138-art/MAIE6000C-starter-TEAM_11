"""add derived chunk search index

Revision ID: 7f3a1b2c4d5e
Revises: 445f908b73b4
Create Date: 2026-10-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "7f3a1b2c4d5e"
down_revision: str | None = "445f908b73b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DIMENSIONS = 384


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_search_index",
        sa.Column(
            "chunk_id",
            sa.String(length=36),
            sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_terms", sa.Text(), nullable=False),
        sa.Column(
            "embedding",
            Vector(DIMENSIONS) if postgres else sa.JSON(none_as_null=True),
            nullable=True,
        ),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    if postgres:
        op.execute(
            "CREATE INDEX ix_chunk_search_index_keyword "
            "ON chunk_search_index USING gin (to_tsvector('simple', search_terms))"
        )


def downgrade() -> None:
    op.drop_table("chunk_search_index")
    # The vector extension may be shared by other modules; do not remove it.
