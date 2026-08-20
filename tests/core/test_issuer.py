from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from securities_master.core.tables import (
    IDENTIFIER_TYPES,
    SECURITY_TYPES,
    issuer,
    security,
    security_identifier,
)


def _make_issuer(conn, cik="0000320193", name="Apple Inc.") -> int:
    return conn.execute(
        issuer.insert()
        .values(
            cik=cik,
            name=name,
            entity_type="operating",
            sic_code="3571",
            sic_description="Electronic Computers",
        )
        .returning(issuer.c.issuer_id)
    ).scalar_one()


def test_issuer_rejects_a_duplicate_cik(conn):
    _make_issuer(conn)
    with pytest.raises(IntegrityError):
        _make_issuer(conn, name="Impostor Inc.")


def test_issuer_allows_null_sec_fields(conn):
    """A filer whose submissions fetch failed keeps NULLs, never a guess."""
    conn.execute(
        issuer.insert().values(
            cik="0000000111",
            name="Unfetched Corp",
            entity_type=None,
            sic_code=None,
            sic_description=None,
        )
    )


def test_one_issuer_can_own_two_securities(conn):
    """The case this whole phase exists for: Alphabet's GOOGL and GOOG."""
    issuer_id = _make_issuer(conn, cik="0001652044", name="Alphabet Inc.")
    for ticker in ("GOOGL", "GOOG"):
        security_id = conn.execute(
            security.insert()
            .values(
                issuer_id=issuer_id,
                security_type="common_stock",
                status="active",
                first_seen_date=date(2026, 8, 19),
            )
            .returning(security.c.security_id)
        ).scalar_one()
        conn.execute(
            security_identifier.insert().values(
                security_id=security_id,
                id_type="ticker",
                id_value=ticker,
                valid_from=date(2026, 8, 19),
                valid_to=None,
            )
        )
    count = conn.execute(
        select(security.c.security_id).where(security.c.issuer_id == issuer_id)
    ).scalars().all()
    assert len(count) == 2


def test_security_requires_an_issuer(conn):
    with pytest.raises(IntegrityError):
        conn.execute(
            security.insert().values(
                issuer_id=999999,
                security_type="common_stock",
                status="active",
                first_seen_date=date(2026, 8, 19),
            )
        )


def test_unknown_is_an_accepted_security_type(conn):
    issuer_id = _make_issuer(conn)
    conn.execute(
        security.insert().values(
            issuer_id=issuer_id,
            security_type="unknown",
            status="active",
            first_seen_date=date(2026, 8, 19),
        )
    )
    assert "unknown" in SECURITY_TYPES


def test_cik_is_no_longer_a_security_identifier(conn):
    """CIK moved to issuer; the identifier CHECK must reject it."""
    assert "cik" not in IDENTIFIER_TYPES
    issuer_id = _make_issuer(conn)
    security_id = conn.execute(
        security.insert()
        .values(
            issuer_id=issuer_id,
            security_type="common_stock",
            status="active",
            first_seen_date=date(2026, 8, 19),
        )
        .returning(security.c.security_id)
    ).scalar_one()
    with pytest.raises(IntegrityError):
        conn.execute(
            security_identifier.insert().values(
                security_id=security_id,
                id_type="cik",
                id_value="0000320193",
                valid_from=date(2026, 8, 19),
                valid_to=None,
            )
        )
