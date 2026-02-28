"""add entity dictionary table

Revision ID: 0002_entity_dictionary
Revises: 0001_init
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_entity_dictionary"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_dictionary",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("entity_name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("entity_kind", "entity_name", name="uq_entity_kind_name"),
    )


def downgrade() -> None:
    op.drop_table("entity_dictionary")
