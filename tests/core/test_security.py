import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import issuer, security


def _make_issuer(conn) -> int:
    return conn.execute(
        issuer.insert()
        .values(cik=uuid.uuid4().hex[:10], name="Test Issuer")
        .returning(issuer.c.issuer_id)
    ).scalar_one()


def test_insert_returns_generated_id(conn):
    issuer_id = _make_issuer(conn)
    security_id = conn.execute(
        security.insert()
        .values(
            issuer_id=issuer_id,
            security_type="common_stock",
            status="active",
            first_seen_date=date(2026, 8, 16),
        )
        .returning(security.c.security_id)
    ).scalar_one()
    assert isinstance(security_id, int)


def test_rejects_unknown_security_type(conn):
    issuer_id = _make_issuer(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security.insert().values(
                issuer_id=issuer_id,
                security_type="not_a_real_type",
                status="active",
                first_seen_date=date(2026, 8, 16),
            )
        )


def test_rejects_unknown_status(conn):
    issuer_id = _make_issuer(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security.insert().values(
                issuer_id=issuer_id,
                security_type="common_stock",
                status="hibernating",
                first_seen_date=date(2026, 8, 16),
            )
        )


def test_has_no_ticker_column():
    """P2: a ticker column here is the fatal design error this schema avoids."""
    assert "ticker" not in security.c
