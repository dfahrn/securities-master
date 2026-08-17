"""landing.edgar_company_tickers

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edgar_company_tickers",
        sa.Column("landing_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.Text, nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False),
        schema="landing",
    )


def downgrade() -> None:
    op.drop_table("edgar_company_tickers", schema="landing")
