from datetime import datetime, timezone

from securities_master.cli import latest_exchange_landing_id
from securities_master.landing.tables import edgar_company_tickers_exchange

FETCHED = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _land(conn, digest):
    return conn.execute(
        edgar_company_tickers_exchange.insert()
        .values(
            fetched_at=FETCHED,
            payload_hash=digest,
            payload={"fields": [], "data": []},
        )
        .returning(edgar_company_tickers_exchange.c.landing_id)
    ).scalar_one()


def test_returns_none_when_nothing_is_landed(conn):
    assert latest_exchange_landing_id(conn) is None


def test_returns_the_most_recent_landing_id(conn):
    first = _land(conn, "h1")
    second = _land(conn, "h2")
    assert second > first
    assert latest_exchange_landing_id(conn) == second
