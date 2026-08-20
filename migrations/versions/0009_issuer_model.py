"""issuer model: CIK moves off security_identifier onto its own table

Revision ID: 0009
Revises: 0008

DESTRUCTIVE. This truncates every core table and relies on the rebuild
reading from `landing`. That is safe for exactly one reason: principle P4
(`core` is fully derivable from `landing`). Up to this commit, P4 was pinned
by `test_normalize_replays_identically_from_landing` in
tests/normalize/test_edgar.py; this same commit retires that test alongside
the module it covered, because `issuer_id NOT NULL` and the narrowed
identifier CHECK make that normalizer's inserts illegal. The property goes
unpinned for exactly one commit: the exchange normalizer carries its own
`test_normalize_replays_identically_from_landing` against the new rebuild
path, re-pinning P4 there. The downgrade is LOSSY — it restores the schema
but not the data; re-run normalization afterwards.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "TRUNCATE core.security_identifier, core.security_listing, core.security "
        "RESTART IDENTITY CASCADE"
    )

    op.create_table(
        "issuer",
        sa.Column("issuer_id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("cik", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=True),
        sa.Column("sic_code", sa.Text, nullable=True),
        sa.Column("sic_description", sa.Text, nullable=True),
        schema="core",
    )

    # NOT NULL without a default is only possible because the TRUNCATE above
    # emptied the table.
    op.add_column(
        "security",
        sa.Column("issuer_id", sa.BigInteger, nullable=False),
        schema="core",
    )
    op.create_foreign_key(
        "security_issuer_id_fkey",
        "security",
        "issuer",
        ["issuer_id"],
        ["issuer_id"],
        source_schema="core",
        referent_schema="core",
    )
    op.create_index(
        "security_by_issuer", "security", ["issuer_id"], schema="core"
    )

    op.drop_constraint("security_type_valid", "security", schema="core", type_="check")
    op.create_check_constraint(
        "security_type_valid",
        "security",
        "security_type IN ('common_stock', 'etf', 'adr', 'unknown')",
        schema="core",
    )

    op.drop_constraint(
        "identifier_type_valid", "security_identifier", schema="core", type_="check"
    )
    op.create_check_constraint(
        "identifier_type_valid",
        "security_identifier",
        "id_type IN ('ticker', 'cusip', 'isin', 'figi')",
        schema="core",
    )

    op.execute(
        "INSERT INTO core.exchange (mic, name, country, timezone) "
        "VALUES ('BATS', 'Cboe BZX Exchange', 'US', 'America/New_York')"
    )
    # ARCX was seeded in Phase 1 and no data ever referenced it.
    op.execute("DELETE FROM core.exchange WHERE mic = 'ARCX'")


def downgrade() -> None:
    op.execute(
        "TRUNCATE core.security_identifier, core.security_listing, core.security "
        "RESTART IDENTITY CASCADE"
    )
    op.execute(
        "INSERT INTO core.exchange (mic, name, country, timezone) "
        "VALUES ('ARCX', 'NYSE Arca', 'US', 'America/New_York')"
    )
    op.execute("DELETE FROM core.exchange WHERE mic = 'BATS'")
    op.drop_constraint(
        "identifier_type_valid", "security_identifier", schema="core", type_="check"
    )
    op.create_check_constraint(
        "identifier_type_valid",
        "security_identifier",
        "id_type IN ('ticker', 'cusip', 'isin', 'figi', 'cik')",
        schema="core",
    )
    op.drop_constraint("security_type_valid", "security", schema="core", type_="check")
    op.create_check_constraint(
        "security_type_valid",
        "security",
        "security_type IN ('common_stock', 'etf', 'adr')",
        schema="core",
    )
    op.drop_index("security_by_issuer", "security", schema="core")
    op.drop_constraint(
        "security_issuer_id_fkey", "security", schema="core", type_="foreignkey"
    )
    op.drop_column("security", "issuer_id", schema="core")
    op.drop_table("issuer", schema="core")
