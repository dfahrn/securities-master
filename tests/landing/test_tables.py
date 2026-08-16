from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from securities_master.landing.tables import edgar_company_tickers


def test_stores_json_payload(conn):
    conn.execute(
        edgar_company_tickers.insert().values(
            fetched_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            payload_hash="abc123",
            payload={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
        )
    )


def test_identical_payload_is_rejected(conn):
    """Idempotency: re-fetching unchanged data must not create a second row."""
    values = {
        "fetched_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "payload_hash": "abc123",
        "payload": {"0": {"cik_str": 320193, "ticker": "AAPL"}},
    }
    conn.execute(edgar_company_tickers.insert().values(**values))
    with pytest.raises(IntegrityError):
        conn.execute(edgar_company_tickers.insert().values(**values))
