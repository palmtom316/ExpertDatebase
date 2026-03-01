"""Add doc_pages table with tsvector full-text index for PG-BM25 sparse retrieval.

Revision ID: 0003
Revises: 0002_entity_dictionary
Create Date: 2026-03-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_doc_pages_tsvector"
down_revision = "0002_entity_dictionary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create doc_pages table for per-page text used by PG-BM25 sparse retrieval
    op.create_table(
        "doc_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("doc_id", sa.String(64), nullable=False, index=True),
        sa.Column("version_id", sa.String(64), nullable=False, index=True),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_path", sa.String(512), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("doc_id", "page_no", name="uq_doc_pages_doc_page"),
    )

    # GIN index on tsvector for fast full-text search
    op.create_index(
        "idx_doc_pages_tsv",
        "doc_pages",
        ["tsv"],
        postgresql_using="gin",
    )

    # Trigger: auto-update tsv on insert/update
    op.execute("""
        CREATE OR REPLACE FUNCTION doc_pages_tsv_update() RETURNS trigger AS $$
        BEGIN
            NEW.tsv := to_tsvector('simple', COALESCE(NEW.text, ''));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER doc_pages_tsv_trigger
        BEFORE INSERT OR UPDATE OF text
        ON doc_pages
        FOR EACH ROW EXECUTE FUNCTION doc_pages_tsv_update();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS doc_pages_tsv_trigger ON doc_pages")
    op.execute("DROP FUNCTION IF EXISTS doc_pages_tsv_update()")
    op.drop_index("idx_doc_pages_tsv", table_name="doc_pages")
    op.drop_table("doc_pages")
