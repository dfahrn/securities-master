"""core.security

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security",
        sa.Column("security_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("security_type", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("first_seen_date", sa.Date, nullable=False),
        sa.CheckConstraint(
            "security_type IN ('common_stock', 'etf', 'adr')",
            name="security_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'delisted')", name="security_status_valid"
        ),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("security", schema="core")
