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


def downgrade() -> None:
    op.drop_table("documents")
