from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import security, security_listing


def _make_security(conn) -> int:
    return conn.execute(
        security.insert()
        .values(
            security_type="common_stock",
            status="active",
            first_seen_date=date(2000, 1, 1),
        )
        .returning(security.c.security_id)
    ).scalar_one()


def test_listing_records_delisting(conn):
    sid = _make_security(conn)
    conn.execute(
        security_listing.insert().values(
            security_id=sid,
            exchange_mic="XNYS",
            valid_from=date(1994, 5, 1),
            valid_to=date(2008, 9, 16),
            delisting_reason="bankruptcy",
        )
    )


def test_rejects_unknown_exchange(conn):
    sid = _make_security(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic="XFAKE",
                valid_from=date(1994, 5, 1),
                valid_to=None,
                delisting_reason=None,
            )
        )


def test_rejects_inverted_range(conn):
    sid = _make_security(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic="XNYS",
                valid_from=date(2008, 1, 1),
                valid_to=date(1994, 1, 1),
                delisting_reason=None,
            )
        )
