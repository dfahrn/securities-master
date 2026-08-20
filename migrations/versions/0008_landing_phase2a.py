"""landing tables for the exchange file and per-filer submissions

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edgar_company_tickers_exchange",
        sa.Column("landing_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.Text, nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False),
        schema="landing",
    )
    op.create_table(
        "edgar_submissions",
        sa.Column("landing_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("cik", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.UniqueConstraint("cik", "payload_hash", name="edgar_submissions_cik_hash_key"),
        schema="landing",
    )
    # The fetch loop's run-scoped resume reads (cik, fetched_at) for every
    # filer on every run; without this it seq-scans a table that grows by
    # ~8,000 rows per run.
    op.create_index(
        "edgar_submissions_cik_fetched_at",
        "edgar_submissions",
        ["cik", "fetched_at"],
        schema="landing",
    )


def downgrade() -> None:
    op.drop_table("edgar_submissions", schema="landing")
    op.drop_table("edgar_company_tickers_exchange", schema="landing")
