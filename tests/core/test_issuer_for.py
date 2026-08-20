from datetime import date

import pytest

from securities_master.core.identity import Issuer, issuer_for
from securities_master.core.tables import issuer, security


def _seed(conn, entity_type="operating", sic="3571"):
    issuer_id = conn.execute(
        issuer.insert()
        .values(
            cik="0000320193",
            name="Apple Inc.",
            entity_type=entity_type,
            sic_code=sic,
            sic_description="Electronic Computers",
        )
        .returning(issuer.c.issuer_id)
    ).scalar_one()
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
    return issuer_id, security_id


def test_returns_the_owning_issuer(conn):
    issuer_id, security_id = _seed(conn)
    found = issuer_for(conn, security_id)
    assert isinstance(found, Issuer)
    assert found.issuer_id == issuer_id
    assert found.cik == "0000320193"
    assert found.entity_type == "operating"
    assert found.sic_code == "3571"


def test_null_sec_fields_survive_the_round_trip(conn):
    _, security_id = _seed(conn, entity_type=None, sic=None)
    found = issuer_for(conn, security_id)
    assert found.entity_type is None
    assert found.sic_code is None


def test_unknown_security_raises(conn):
    with pytest.raises(LookupError):
        issuer_for(conn, 999999)
