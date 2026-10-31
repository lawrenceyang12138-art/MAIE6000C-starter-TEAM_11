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


_TOKEN_COLUMNS = {
    "chunk_id": (sa.String(length=36), False),
    "model_id": (sa.String(length=120), False),
    "model_revision": (sa.String(length=64), False),
    "token_dimensions": (sa.Integer(), False),
    "token_count": (sa.Integer(), False),
    "token_vectors": (sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), False),
    "text_sha256": (sa.String(length=64), False),
    "created_at": (sa.DateTime(timezone=True), False),
    "updated_at": (sa.DateTime(timezone=True), False),
}

_PAGE_COLUMNS = {
    "version_id": (sa.String(length=36), False),
    "content_sha256": (sa.String(length=64), False),
    "byte_size": (sa.Integer(), False),
    "parser_revision": (sa.String(length=50), True),
    "page_count": (sa.Integer(), False),
    "policy_revision": (sa.String(length=50), False),
    "created_at": (sa.DateTime(timezone=True), False),
    "updated_at": (sa.DateTime(timezone=True), False),
}


def _create_token_sidecar() -> None:
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


def _create_page_sidecar() -> None:
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


def _type_signature(type_, dialect) -> str:
    return " ".join(str(type_.compile(dialect=dialect)).upper().split())


def _validate_existing_table(
    bind,
    table_name: str,
    expected_columns: dict,
    primary_key: list[str],
    referred_table: str,
    check_constraint_names: set[str],
) -> None:
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    if set(columns) != set(expected_columns):
        raise RuntimeError(
            f"incompatible {table_name} columns: "
            f"expected {sorted(expected_columns)}, found {sorted(columns)}"
        )
    for name, (expected_type, expected_nullable) in expected_columns.items():
        actual = columns[name]
        if _type_signature(actual["type"], bind.dialect) != _type_signature(
            expected_type, bind.dialect
        ):
            raise RuntimeError(
                f"incompatible {table_name}.{name} type; manual migration required"
            )
        if actual["nullable"] != expected_nullable:
            raise RuntimeError(
                f"incompatible {table_name}.{name} nullability; manual migration required"
            )
    actual_primary_key = inspector.get_pk_constraint(table_name)["constrained_columns"]
    if actual_primary_key != primary_key:
        raise RuntimeError(
            f"incompatible {table_name} primary key: {actual_primary_key}"
        )
    foreign_keys = inspector.get_foreign_keys(table_name)
    if not any(
        foreign_key["constrained_columns"] == primary_key
        and foreign_key["referred_table"] == referred_table
        and foreign_key["referred_columns"] == ["id"]
        and (foreign_key.get("options") or {}).get("ondelete") == "CASCADE"
        for foreign_key in foreign_keys
    ):
        raise RuntimeError(f"incompatible {table_name} foreign key")
    actual_checks = {
        check["name"] for check in inspector.get_check_constraints(table_name)
    }
    if not check_constraint_names <= actual_checks:
        raise RuntimeError(
            f"incompatible {table_name} constraints: missing "
            f"{sorted(check_constraint_names - actual_checks)}"
        )


def _ensure_timestamp_defaults(bind, table_name: str) -> None:
    if bind.dialect.name != "postgresql":
        return
    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    for column_name in ("created_at", "updated_at"):
        if columns[column_name].get("default") is None:
            op.alter_column(
                table_name,
                column_name,
                server_default=sa.text("CURRENT_TIMESTAMP"),
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
            )


def _prepare_table(
    bind,
    *,
    table_name: str,
    expected_columns: dict,
    primary_key: list[str],
    referred_table: str,
    check_constraint_names: set[str],
    create,
) -> None:
    if sa.inspect(bind).has_table(table_name):
        _validate_existing_table(
            bind,
            table_name,
            expected_columns,
            primary_key,
            referred_table,
            check_constraint_names,
        )
        _ensure_timestamp_defaults(bind, table_name)
    else:
        create()


def upgrade() -> None:
    bind = op.get_bind()
    _prepare_table(
        bind,
        table_name="chunk_token_search_index",
        expected_columns=_TOKEN_COLUMNS,
        primary_key=["chunk_id"],
        referred_table="source_chunks",
        check_constraint_names=set(),
        create=_create_token_sidecar,
    )
    _prepare_table(
        bind,
        table_name="version_page_search_metadata",
        expected_columns=_PAGE_COLUMNS,
        primary_key=["version_id"],
        referred_table="file_versions",
        check_constraint_names={
            "ck_version_page_count_positive",
            "ck_version_page_byte_size_nonnegative",
        },
        create=_create_page_sidecar,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Drop derived data before older migrations remove its canonical FK
    # targets. Keeping these tables breaks the documented downgrade to the
    # starter revision. Source text, identities and reviews remain at 0004;
    # normal indexing can rebuild these caches after upgrading again.
    if inspector.has_table("version_page_search_metadata"):
        op.drop_table("version_page_search_metadata")
    if inspector.has_table("chunk_token_search_index"):
        op.drop_table("chunk_token_search_index")
