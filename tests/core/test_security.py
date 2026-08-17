from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import security


def test_insert_returns_generated_id(conn):
    security_id = conn.execute(
        security.insert()
        .values(
            security_type="common_stock",
            status="active",
            first_seen_date=date(2026, 8, 16),
        )
        .returning(security.c.security_id)
    ).scalar_one()
    assert isinstance(security_id, int)


def test_rejects_unknown_security_type(conn):
    with pytest.raises(IntegrityError):
        conn.execute(
            security.insert().values(
                security_type="not_a_real_type",
                status="active",
                first_seen_date=date(2026, 8, 16),
            )
        )


def test_rejects_unknown_status(conn):
    with pytest.raises(IntegrityError):
        conn.execute(
            security.insert().values(
                security_type="common_stock",
                status="hibernating",
                first_seen_date=date(2026, 8, 16),
            )
        )


def test_has_no_ticker_column():
    """P2: a ticker column here is the fatal design error this schema avoids."""
    assert "ticker" not in security.c
