"""index core.security_identifier(security_id)

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # identifiers_for() filters on security_id alone. The existing indexes are
    # the PK, (id_type, id_value, valid_from), and the GiST exclusion index --
    # none of which can serve that predicate, so every call sequential-scanned
    # the whole table.
    op.execute(
        """
        CREATE INDEX security_identifier_by_security
        ON core.security_identifier (security_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX core.security_identifier_by_security")
