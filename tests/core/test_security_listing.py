import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import issuer, security, security_listing


def _make_issuer(conn) -> int:
    return conn.execute(
        issuer.insert()
        .values(cik=uuid.uuid4().hex[:10], name="Test Issuer")
        .returning(issuer.c.issuer_id)
    ).scalar_one()


def _make_security(conn) -> int:
    return conn.execute(
        security.insert()
        .values(
            issuer_id=_make_issuer(conn),
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


def test_rejects_zero_length_range(conn):
    """Pins `valid_to > valid_from` against a flip to `>=`.

    The inverted-range test above fails under both operators. A listing that
    spans no days is not a listing.
    """
    sid = _make_security(conn)
    with pytest.raises(IntegrityError, match="listing_range_valid"):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic="XNYS",
                valid_from=date(2008, 1, 1),
                valid_to=date(2008, 1, 1),
                delisting_reason=None,
            )
        )


def test_overlapping_same_venue_listings_are_rejected(conn):
    """P2: a time-ranged relationship must not overlap itself.

    Two open listings for one security on one venue is not a dual listing,
    it is a duplicate. Without this constraint the blank-ticker path in the
    exchange normalizer — which writes a security and a listing but no
    identifier — bypasses every structural guard `core` has.
    """
    sid = _make_security(conn)
    conn.execute(
        security_listing.insert().values(
            security_id=sid,
            exchange_mic="XNYS",
            valid_from=date(1994, 5, 1),
            valid_to=None,
            delisting_reason=None,
        )
    )
    with pytest.raises(IntegrityError, match="security_listing_no_overlap"):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic="XNYS",
                valid_from=date(2008, 1, 1),
                valid_to=None,
                delisting_reason=None,
            )
        )


def test_adjacent_same_venue_listings_are_accepted(conn):
    """Ranges are half-open: a relisting may start the day the last one ends."""
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
    conn.execute(
        security_listing.insert().values(
            security_id=sid,
            exchange_mic="XNYS",
            valid_from=date(2008, 9, 16),
            valid_to=None,
            delisting_reason=None,
        )
    )
    mics = conn.execute(
        select(security_listing.c.exchange_mic, security_listing.c.valid_from)
        .where(security_listing.c.security_id == sid)
        .order_by(security_listing.c.valid_from)
    ).all()
    assert mics == [("XNYS", date(1994, 5, 1)), ("XNYS", date(2008, 9, 16))]


def test_one_security_may_list_on_two_venues_at_once(conn):
    """The dual listing the exclusion key deliberately permits.

    Keying on `security_id` alone would forbid this, and Phase 4 needs it.
    """
    sid = _make_security(conn)
    for mic in ("XNYS", "XNAS"):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic=mic,
                valid_from=date(2008, 1, 1),
                valid_to=None,
                delisting_reason=None,
            )
        )
    venues = conn.execute(
        select(security_listing.c.exchange_mic)
        .where(security_listing.c.security_id == sid)
        .order_by(security_listing.c.exchange_mic)
    ).scalars().all()
    assert venues == ["XNAS", "XNYS"]


def test_two_securities_may_share_a_venue_and_a_range(conn):
    """Guards the other half of the key.

    A constraint omitting `security_id WITH =` passes every other test in
    this file, yet would permit only one listing per venue in the entire
    database at a time.
    """
    a = _make_security(conn)
    b = _make_security(conn)
    for sid in (a, b):
        conn.execute(
            security_listing.insert().values(
                security_id=sid,
                exchange_mic="XNYS",
                valid_from=date(2008, 1, 1),
                valid_to=None,
                delisting_reason=None,
            )
        )
    listed = conn.execute(
        select(security_listing.c.security_id)
        .where(security_listing.c.security_id.in_([a, b]))
        .order_by(security_listing.c.security_id)
    ).scalars().all()
    assert listed == sorted([a, b])
