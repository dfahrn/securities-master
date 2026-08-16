from datetime import date, datetime, timezone

import httpx
from sqlalchemy import func, select

from securities_master.core.tables import security, security_identifier
from securities_master.ingest.edgar import EdgarAdapter
from securities_master.ingest.land import land_company_tickers
from securities_master.normalize.edgar import normalize_company_tickers

SAMPLE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}
NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)
AS_OF = date(2026, 8, 16)


def _adapter(payload=SAMPLE) -> EdgarAdapter:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    return EdgarAdapter(
        user_agent="test test@example.com",
        client=httpx.Client(transport=transport),
    )


def test_landing_then_normalize_creates_securities(conn):
    landing_id = land_company_tickers(conn, _adapter(), now=NOW)
    created = normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    assert created == 2
    total = conn.execute(select(func.count()).select_from(security)).scalar_one()
    assert total == 2


def test_normalize_creates_ticker_and_cik_identifiers(conn):
    landing_id = land_company_tickers(conn, _adapter(), now=NOW)
    normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    rows = conn.execute(
        select(security_identifier.c.id_type, security_identifier.c.id_value)
        .order_by(security_identifier.c.id_type, security_identifier.c.id_value)
    ).all()
    assert ("cik", "0000320193") in rows
    assert ("ticker", "AAPL") in rows
    assert len(rows) == 4


def test_identifier_ranges_open_at_as_of_date(conn):
    landing_id = land_company_tickers(conn, _adapter(), now=NOW)
    normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    row = conn.execute(
        select(security_identifier.c.valid_from, security_identifier.c.valid_to)
        .where(security_identifier.c.id_value == "AAPL")
    ).one()
    assert row.valid_from == AS_OF
    assert row.valid_to is None


def test_landing_is_idempotent_for_unchanged_payload(conn):
    first = land_company_tickers(conn, _adapter(), now=NOW)
    second = land_company_tickers(conn, _adapter(), now=NOW)
    assert first is not None
    assert second is None


def test_normalize_is_idempotent(conn):
    landing_id = land_company_tickers(conn, _adapter(), now=NOW)
    normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    created_again = normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    assert created_again == 0
    total = conn.execute(select(func.count()).select_from(security)).scalar_one()
    assert total == 2
