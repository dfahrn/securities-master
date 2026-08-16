from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

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
    result = normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    assert result.created == 2
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
    result_again = normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    assert result_again.created == 0
    total = conn.execute(select(func.count()).select_from(security)).scalar_one()
    assert total == 2


def test_ticker_reassigned_to_new_cik_currently_fails(conn):
    """Documents a known Phase 4 gap, deferred deliberately.

    Reassigning a ticker to a different CIK needs the incumbent range closed
    out first. Until Phase 4 adds that, the second assignment collides with
    the exclusion constraint. This test asserts today's behaviour so the gap
    is visible; it will fail loudly when Phase 4 fixes it, which is the point.
    """
    first = {"0": {"cik_str": 111, "ticker": "XYZ", "title": "First Corp"}}
    second = {"0": {"cik_str": 222, "ticker": "XYZ", "title": "Second Corp"}}
    landing_one = land_company_tickers(conn, _adapter(first), now=NOW)
    normalize_company_tickers(conn, landing_one, as_of=AS_OF)
    landing_two = land_company_tickers(conn, _adapter(second), now=NOW)
    with pytest.raises(IntegrityError, match="security_identifier_no_overlap"):
        normalize_company_tickers(conn, landing_two, as_of=AS_OF)


def test_repeated_cik_within_one_payload_is_skipped_and_counted(conn):
    payload = {
        "0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "1": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    }
    landing_id = land_company_tickers(conn, _adapter(payload), now=NOW)
    result = normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    assert result.created == 1
    assert result.skipped_duplicate_cik == 1


def test_second_payload_adds_only_new_company(conn):
    landing_one = land_company_tickers(conn, _adapter(), now=NOW)
    normalize_company_tickers(conn, landing_one, as_of=AS_OF)

    expanded = dict(SAMPLE)
    expanded["2"] = {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"}
    landing_two = land_company_tickers(conn, _adapter(expanded), now=NOW)
    result = normalize_company_tickers(conn, landing_two, as_of=AS_OF)

    assert result.created == 1
    total = conn.execute(select(func.count()).select_from(security)).scalar_one()
    assert total == 3
