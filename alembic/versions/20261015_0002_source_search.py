"""Source search contract proposed by member C for integration by A.

Revision ID: 20261015_0002
Revises: 20260713_0001
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "20261015_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "source_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.String(2048), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_files_sha256", "source_files", ["sha256"])
    op.create_index("ix_source_files_status", "source_files", ["status"])
    op.create_table(
        "source_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_file_id",
            sa.String(36),
            sa.ForeignKey("source_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("embedding_dimensions", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_file_id", "version_number", name="uq_source_versions_file_version"
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_source_versions_number"),
    )
    for column in ("source_file_id", "status", "is_current"):
        op.create_index(f"ix_source_versions_{column}", "source_versions", [column])
    op.create_index(
        "uq_source_versions_current_file",
        "source_versions",
        ["source_file_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_table(
        "source_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_version_id",
            sa.String(36),
            sa.ForeignKey("source_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("search_terms", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(384) if postgres else sa.JSON(none_as_null=True)),
        sa.Column("embedding_model", sa.String(120)),
        sa.Column("embedding_dimensions", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_version_id", "chunk_index", name="uq_source_chunks_version_index"
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_source_chunks_index"),
        sa.CheckConstraint(
            "page_start >= 1 AND page_end >= page_start", name="ck_source_chunks_pages"
        ),
    )
    op.create_index("ix_source_chunks_source_version_id", "source_chunks", ["source_version_id"])
    if postgres:
        op.execute(
            "CREATE INDEX ix_source_chunks_keyword ON source_chunks "
            "USING gin (to_tsvector('simple', search_terms))"
        )


def downgrade() -> None:
    op.drop_table("source_chunks")
    op.drop_table("source_versions")
    op.drop_table("source_files")
    # The vector extension may be shared by other modules; do not remove it.
