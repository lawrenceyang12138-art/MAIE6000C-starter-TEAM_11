"""Add the search sidecar for canonical source chunks.

Revision ID: 20261015_0002
Revises: 445f908b73b4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "20261015_0002"
down_revision = "445f908b73b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_search_index",
        sa.Column(
            "chunk_id",
            sa.String(36),
            sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_terms", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384) if postgres else sa.JSON(none_as_null=True)),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("embedding_dimensions", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    if postgres:
        op.execute(
            "CREATE INDEX ix_chunk_search_index_keyword ON chunk_search_index "
            "USING gin (to_tsvector('simple', search_terms))"
        )


def downgrade() -> None:
    op.drop_table("chunk_search_index")
