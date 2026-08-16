from datetime import date

from sqlalchemy import select

from securities_master.core.identity import identifiers_for, resolve
from securities_master.core.tables import security, security_identifier


def _security_with_ticker(conn, ticker, valid_from, valid_to) -> int:
    security_id = conn.execute(
        security.insert()
        .values(
            security_type="common_stock",
            status="active",
            first_seen_date=valid_from,
        )
        .returning(security.c.security_id)
    ).scalar_one()
    conn.execute(
        security_identifier.insert().values(
            security_id=security_id,
            id_type="ticker",
            id_value=ticker,
            valid_from=valid_from,
            valid_to=valid_to,
        )
    )
    return security_id


def test_resolves_within_range(conn):
    sid = _security_with_ticker(conn, "XYZ", date(2005, 1, 1), date(2013, 6, 1))
    assert resolve(conn, "XYZ", date(2008, 3, 1)) == sid


def test_resolve_is_case_insensitive(conn):
    sid = _security_with_ticker(conn, "XYZ", date(2005, 1, 1), None)
    assert resolve(conn, "xyz", date(2008, 3, 1)) == sid


def test_returns_none_before_range(conn):
    _security_with_ticker(conn, "XYZ", date(2005, 1, 1), date(2013, 6, 1))
    assert resolve(conn, "XYZ", date(2001, 1, 1)) is None


def test_end_date_is_exclusive(conn):
    _security_with_ticker(conn, "XYZ", date(2005, 1, 1), date(2013, 6, 1))
    assert resolve(conn, "XYZ", date(2013, 6, 1)) is None


def test_reassigned_ticker_resolves_to_the_right_company(conn):
    """The central correctness property of the identity layer."""
    old = _security_with_ticker(conn, "XYZ", date(2005, 1, 1), date(2013, 6, 1))
    new = _security_with_ticker(conn, "XYZ", date(2019, 3, 1), None)
    assert resolve(conn, "XYZ", date(2008, 3, 1)) == old
    assert resolve(conn, "XYZ", date(2024, 3, 1)) == new
    assert resolve(conn, "XYZ", date(2015, 3, 1)) is None


def test_identifiers_for_returns_active_identifiers(conn):
    sid = _security_with_ticker(conn, "XYZ", date(2005, 1, 1), None)
    conn.execute(
        security_identifier.insert().values(
            security_id=sid,
            id_type="cik",
            id_value="0000320193",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )
    assert identifiers_for(conn, sid, date(2020, 1, 1)) == {
        "ticker": "XYZ",
        "cik": "0000320193",
    }
