"""core.exchange

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange",
        sa.Column("mic", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("country", sa.Text, nullable=False),
        sa.Column("timezone", sa.Text, nullable=False),
        schema="core",
    )
    op.execute(
        """
        INSERT INTO core.exchange (mic, name, country, timezone) VALUES
          ('XNYS', 'New York Stock Exchange', 'US', 'America/New_York'),
          ('XNAS', 'Nasdaq Stock Market',     'US', 'America/New_York'),
          ('ARCX', 'NYSE Arca',               'US', 'America/New_York')
        """
    )


def downgrade() -> None:
    op.drop_table("exchange", schema="core")
