"""Initial schema.

Revision ID: 0001_init
Revises:
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("doc_id", sa.String(length=64), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("mineru_json_key", sa.String(length=1024), nullable=True),
        sa.Column("mineru_md_key", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("doc_id", sa.String(length=64), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", sa.String(length=64), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("chapter_id", sa.String(length=64), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("block_ids", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("doc_id", sa.String(length=64), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", sa.String(length=64), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("source_excerpt", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=True),
        sa.Column("table_id", sa.String(length=64), nullable=True),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "eval_run",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "eval_sample",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("eval_run.id"), nullable=False),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("input_path", sa.String(length=1024), nullable=False),
        sa.Column("truth_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "eval_result",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("eval_run.id"), nullable=False),
        sa.Column("sample_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("score_total", sa.Float(), nullable=False),
        sa.Column("breakdown_json", sa.JSON(), nullable=False),
        sa.Column("output_path", sa.String(length=1024), nullable=False),
        sa.Column("diff_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("eval_result")
    op.drop_table("eval_sample")
    op.drop_table("eval_run")
    op.drop_table("llm_call_log")
    op.drop_table("assets")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
