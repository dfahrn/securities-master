"""create landing and core schemas

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS landing")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    # btree_gist lets a GiST EXCLUDE constraint mix equality on scalar
    # columns with overlap on a range column. Required by Task 5.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
    op.execute("DROP SCHEMA IF EXISTS landing CASCADE")
