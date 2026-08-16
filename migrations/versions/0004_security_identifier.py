"""core.security_identifier with temporal exclusion constraint

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_identifier",
        sa.Column(
            "security_identifier_id", sa.BigInteger, sa.Identity(), primary_key=True
        ),
        sa.Column("security_id", sa.BigInteger, nullable=False),
        sa.Column("id_type", sa.Text, nullable=False),
        sa.Column("id_value", sa.Text, nullable=False),
        sa.Column("valid_from", sa.Date, nullable=False),
        sa.Column("valid_to", sa.Date, nullable=True),
        sa.ForeignKeyConstraint(
            ["security_id"], ["core.security.security_id"]
        ),
        sa.CheckConstraint(
            "id_type IN ('ticker', 'cusip', 'isin', 'figi', 'cik')",
            name="identifier_type_valid",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="identifier_range_valid"
        ),
        schema="core",
    )
    # The core invariant of the securities master: one (id_type, id_value)
    # may map to at most one security on any given day. '[)' makes the range
    # half-open so an identifier can be reassigned on the day the prior
    # assignment ends. A NULL valid_to yields an unbounded upper edge.
    op.execute(
        """
        ALTER TABLE core.security_identifier
        ADD CONSTRAINT security_identifier_no_overlap
        EXCLUDE USING gist (
            id_type  WITH =,
            id_value WITH =,
            daterange(valid_from, valid_to, '[)') WITH &&
        )
        """
    )
    op.execute(
        """
        CREATE INDEX security_identifier_lookup
        ON core.security_identifier (id_type, id_value, valid_from)
        """
    )


def downgrade() -> None:
    op.drop_table("security_identifier", schema="core")
