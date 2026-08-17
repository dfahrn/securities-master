from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import security, security_identifier


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


def test_same_ticker_reused_after_gap_is_allowed(conn):
    """A delisted ticker reassigned to an unrelated company is legal."""
    old = _make_security(conn)
    new = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=old,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=date(2013, 6, 1),
        )
    )
    conn.execute(
        security_identifier.insert().values(
            security_id=new,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2019, 3, 1),
            valid_to=None,
        )
    )


def test_overlapping_ticker_ranges_are_rejected(conn):
    """Two securities may not hold the same ticker on the same day."""
    a = _make_security(conn)
    b = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=a,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=date(2013, 6, 1),
        )
    )
    with pytest.raises(IntegrityError, match="security_identifier_no_overlap"):
        conn.execute(
            security_identifier.insert().values(
                security_id=b,
                id_type="ticker",
                id_value="XYZ",
                valid_from=date(2010, 1, 1),
                valid_to=None,
            )
        )


def test_open_ended_range_blocks_later_assignment(conn):
    """valid_to IS NULL means 'to infinity', so nothing may follow it."""
    a = _make_security(conn)
    b = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=a,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )
    with pytest.raises(IntegrityError, match="security_identifier_no_overlap"):
        conn.execute(
            security_identifier.insert().values(
                security_id=b,
                id_type="ticker",
                id_value="XYZ",
                valid_from=date(2020, 1, 1),
                valid_to=None,
            )
        )


def test_adjacent_ranges_do_not_overlap(conn):
    """Ranges are half-open, so valid_to == next valid_from is legal."""
    a = _make_security(conn)
    b = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=a,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=date(2013, 6, 1),
        )
    )
    conn.execute(
        security_identifier.insert().values(
            security_id=b,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2013, 6, 1),
            valid_to=None,
        )
    )


def test_different_id_types_do_not_collide(conn):
    """A ticker 'XYZ' and a CUSIP 'XYZ' are unrelated keys."""
    a = _make_security(conn)
    b = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=a,
            id_type="ticker",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )
    conn.execute(
        security_identifier.insert().values(
            security_id=b,
            id_type="cusip",
            id_value="XYZ",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )


def test_different_id_values_do_not_collide(conn):
    """Two tickers may of course be active on the same day.

    Guards the other half of the exclusion key: a constraint omitting
    `id_value WITH =` passes every other test in this file, yet would
    permit only one ticker in the entire database at a time.
    """
    a = _make_security(conn)
    b = _make_security(conn)
    conn.execute(
        security_identifier.insert().values(
            security_id=a,
            id_type="ticker",
            id_value="AAPL",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )
    conn.execute(
        security_identifier.insert().values(
            security_id=b,
            id_type="ticker",
            id_value="MSFT",
            valid_from=date(2005, 1, 1),
            valid_to=None,
        )
    )


def test_rejects_unknown_id_type(conn):
    a = _make_security(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security_identifier.insert().values(
                security_id=a,
                id_type="bloomberg_vibes",
                id_value="XYZ",
                valid_from=date(2005, 1, 1),
                valid_to=None,
            )
        )


def test_rejects_inverted_range(conn):
    a = _make_security(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            security_identifier.insert().values(
                security_id=a,
                id_type="ticker",
                id_value="XYZ",
                valid_from=date(2013, 1, 1),
                valid_to=date(2005, 1, 1),
            )
        )


def test_rejects_zero_length_range(conn):
    """Pins `valid_to > valid_from` against a flip to `>=`.

    The inverted-range test above fails under both operators, so it does not
    pin the boundary. A row with valid_to == valid_from spans no days at all:
    it is invisible to `resolve()` on every date and, being an empty range,
    invisible to the exclusion constraint too.
    """
    a = _make_security(conn)
    with pytest.raises(IntegrityError, match="identifier_range_valid"):
        conn.execute(
            security_identifier.insert().values(
                security_id=a,
                id_type="ticker",
                id_value="XYZ",
                valid_from=date(2005, 1, 1),
                valid_to=date(2005, 1, 1),
            )
        )
