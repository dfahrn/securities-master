from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from securities_master.landing.tables import (
    edgar_company_tickers_exchange,
    edgar_submissions,
)

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def test_exchange_file_payload_is_stored(conn):
    conn.execute(
        edgar_company_tickers_exchange.insert().values(
            fetched_at=NOW,
            payload_hash="abc",
            payload={"fields": ["cik", "name", "ticker", "exchange"], "data": []},
        )
    )


def test_exchange_file_rejects_duplicate_hash(conn):
    values = {
        "fetched_at": NOW,
        "payload_hash": "abc",
        "payload": {"fields": [], "data": []},
    }
    conn.execute(edgar_company_tickers_exchange.insert().values(**values))
    with pytest.raises(IntegrityError):
        conn.execute(edgar_company_tickers_exchange.insert().values(**values))


def test_submissions_allows_same_cik_with_a_changed_payload(conn):
    """A filer's payload changes over time; each version is its own row."""
    conn.execute(
        edgar_submissions.insert().values(
            cik="0000320193", fetched_at=NOW, payload_hash="v1", payload={"a": 1}
        )
    )
    conn.execute(
        edgar_submissions.insert().values(
            cik="0000320193", fetched_at=NOW, payload_hash="v2", payload={"a": 2}
        )
    )


def test_submissions_rejects_the_same_cik_and_hash_twice(conn):
    values = {
        "cik": "0000320193",
        "fetched_at": NOW,
        "payload_hash": "v1",
        "payload": {"a": 1},
    }
    conn.execute(edgar_submissions.insert().values(**values))
    with pytest.raises(IntegrityError):
        conn.execute(edgar_submissions.insert().values(**values))


def test_submissions_allows_the_same_hash_under_different_ciks(conn):
    """Two filers can legitimately have identical payloads; only (cik, hash) is unique."""
    conn.execute(
        edgar_submissions.insert().values(
            cik="0000000111", fetched_at=NOW, payload_hash="same", payload={"a": 1}
        )
    )
    conn.execute(
        edgar_submissions.insert().values(
            cik="0000000222", fetched_at=NOW, payload_hash="same", payload={"a": 1}
        )
    )
