"""temporal exclusion on core.security_listing; index landing fetched_at

Revision ID: 0010
Revises: 0009

Two independent fixes, both structural:

1. `core.security_listing` is a time-ranged relationship (P2) and until now
   carried only two foreign keys and a range check. That permitted a security
   holding two identical open listings on the same venue, and permitted
   outright duplicate rows. The exclusion key is (security_id, exchange_mic),
   not security_id alone, so a genuine dual listing — the same security on two
   different venues at the same time — stays legal, which Phase 4 needs.
   `btree_gist` was installed in migration 0001.

2. `landing.edgar_submissions` already has an index on (cik, fetched_at), but
   the fetch loop's `_landed_this_run` filters on `fetched_at` alone and a
   btree cannot seek on a non-leading column. This adds the index the shipped
   query can actually use.
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE core.security_listing
        ADD CONSTRAINT security_listing_no_overlap
        EXCLUDE USING gist (
            security_id  WITH =,
            exchange_mic WITH =,
            daterange(valid_from, valid_to, '[)') WITH &&
        )
        """
    )
    op.execute(
        """
        CREATE INDEX edgar_submissions_fetched_at
        ON landing.edgar_submissions (fetched_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX landing.edgar_submissions_fetched_at")
    op.execute(
        "ALTER TABLE core.security_listing "
        "DROP CONSTRAINT security_listing_no_overlap"
    )
