from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from securities_master.ingest.edgar import EdgarAdapter
from securities_master.ingest.land import land_company_tickers_exchange
from securities_master.landing.tables import edgar_company_tickers_exchange

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)
SAMPLE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
    ],
}


def _adapter(payload=SAMPLE) -> EdgarAdapter:
    return EdgarAdapter(
        user_agent="test test@example.com",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        ),
    )


def test_lands_the_payload_and_returns_its_id(conn):
    landing_id = land_company_tickers_exchange(conn, _adapter(), now=NOW)
    assert isinstance(landing_id, int)
    stored = conn.execute(
        select(edgar_company_tickers_exchange.c.payload).where(
            edgar_company_tickers_exchange.c.landing_id == landing_id
        )
    ).scalar_one()
    assert stored == SAMPLE


def test_unchanged_payload_lands_nothing(conn):
    first = land_company_tickers_exchange(conn, _adapter(), now=NOW)
    second = land_company_tickers_exchange(conn, _adapter(), now=NOW)
    assert first is not None
    assert second is None
    total = conn.execute(
        select(func.count()).select_from(edgar_company_tickers_exchange)
    ).scalar_one()
    assert total == 1


def test_a_changed_payload_lands_a_second_row(conn):
    changed = {
        "fields": SAMPLE["fields"],
        "data": SAMPLE["data"] + [[789019, "MICROSOFT CORP", "MSFT", "Nasdaq"]],
    }
    land_company_tickers_exchange(conn, _adapter(), now=NOW)
    second = land_company_tickers_exchange(conn, _adapter(changed), now=NOW)
    assert second is not None
    # Pins the count the way its sibling's `total == 1` pins the other
    # direction: `is not None` alone would also pass if the second call had
    # somehow returned an id without inserting a row.
    total = conn.execute(
        select(func.count()).select_from(edgar_company_tickers_exchange)
    ).scalar_one()
    assert total == 2
