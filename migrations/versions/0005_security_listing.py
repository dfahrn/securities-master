"""core.security_listing

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_listing",
        sa.Column(
            "security_listing_id", sa.BigInteger, sa.Identity(), primary_key=True
        ),
        sa.Column("security_id", sa.BigInteger, nullable=False),
        sa.Column("exchange_mic", sa.Text, nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.Column("delisting_reason", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["security_id"], ["core.security.security_id"]),
        sa.ForeignKeyConstraint(["exchange_mic"], ["core.exchange.mic"]),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="listing_range_valid"
        ),
        schema="core",
    )


def downgrade() -> None:
    op.drop_table("security_listing", schema="core")
