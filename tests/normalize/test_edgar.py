from datetime import date, datetime, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from securities_master.core.identity import resolve
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
# A fetch date deliberately far from any wall clock a replay could see.
REPLAYED_AT = datetime(2020, 3, 1, 14, 30, tzinfo=timezone.utc)
REPLAYED_ON = date(2020, 3, 1)


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


def test_ticker_change_on_known_cik_is_counted_and_not_applied(conn):
    """The quiet half of the deferred reassignment gap.

    A rename on an unchanged CIK hits the skip branch: the new ticker is
    never created and the stale range stays open-ended, so `resolve()` is
    wrong about *today* with no exception raised. Counted under its own
    field so it is not conflated with a share class this schema cannot
    represent. Phase 4's range close-out logic is what fixes it.
    """
    first = {"0": {"cik_str": 111, "ticker": "XYZ", "title": "First Corp"}}
    renamed = {"0": {"cik_str": 111, "ticker": "ABC", "title": "First Corp"}}
    landing_one = land_company_tickers(conn, _adapter(first), now=NOW)
    normalize_company_tickers(conn, landing_one, as_of=AS_OF)
    original = resolve(conn, "XYZ", AS_OF)

    landing_two = land_company_tickers(conn, _adapter(renamed), now=NOW)
    result = normalize_company_tickers(conn, landing_two, as_of=AS_OF)

    assert result.created == 0
    assert result.skipped_cik_ticker_changed == 1
    assert result.skipped_duplicate_cik == 0

    stale = conn.execute(
        select(security_identifier.c.valid_to).where(
            security_identifier.c.id_value == "XYZ"
        )
    ).scalar_one()
    assert stale is None, "the superseded range is still open-ended"
    assert resolve(conn, "ABC", AS_OF) is None, "the new ticker was never created"
    assert resolve(conn, "XYZ", AS_OF) == original


def test_share_class_skip_is_not_reported_as_a_ticker_change(conn):
    """Re-normalizing a multi-share-class CIK must not flip counters.

    Both GOOGL and GOOG hit the skip branch on a second run, and neither is a
    rename: the recorded ticker is still in the payload.
    """
    payload = {
        "0": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "1": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
    }
    landing_id = land_company_tickers(conn, _adapter(payload), now=NOW)
    normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    result = normalize_company_tickers(conn, landing_id, as_of=AS_OF)

    assert result.created == 0
    assert result.skipped_duplicate_cik == 2
    assert result.skipped_cik_ticker_changed == 0


def test_blank_ticker_is_skipped_without_losing_the_security(conn):
    """One malformed row must not roll back the whole seed transaction.

    Two blank tickers in one payload would collide on the exclusion
    constraint and abort every insert in the run. The entity is still worth
    keeping when only its ticker is unusable, so the security and its CIK
    anchor are created and the blank is counted.
    """
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 111, "ticker": "   ", "title": "Blank One"},
        "2": {"cik_str": 222, "ticker": "", "title": "Blank Two"},
    }
    landing_id = land_company_tickers(conn, _adapter(payload), now=NOW)
    result = normalize_company_tickers(conn, landing_id, as_of=AS_OF)

    assert result.created == 3
    assert result.skipped_blank_ticker == 2
    total = conn.execute(select(func.count()).select_from(security)).scalar_one()
    assert total == 3
    ciks = conn.execute(
        select(security_identifier.c.id_value).where(
            security_identifier.c.id_type == "cik"
        )
    ).scalars().all()
    assert sorted(ciks) == ["0000000111", "0000000222", "0000320193"]
    tickers = conn.execute(
        select(security_identifier.c.id_value).where(
            security_identifier.c.id_type == "ticker"
        )
    ).scalars().all()
    assert tickers == ["AAPL"]


def test_normalize_replays_identically_from_landing(conn):
    """P4: core must be *reproducible* from landing, not merely rebuildable.

    `as_of` defaults to the landing row's own `fetched_at`, so deleting the
    derived rows and normalizing again on a different day reproduces the
    original dates. A wall-clock default would fail this test.
    """
    landing_id = land_company_tickers(conn, _adapter(), now=REPLAYED_AT)
    normalize_company_tickers(conn, landing_id)

    def dates():
        return (
            conn.execute(
                select(security.c.first_seen_date).order_by(security.c.security_id)
            ).scalars().all(),
            conn.execute(
                select(security_identifier.c.valid_from).order_by(
                    security_identifier.c.security_identifier_id
                )
            ).scalars().all(),
        )

    before = dates()
    assert before == ([REPLAYED_ON] * 2, [REPLAYED_ON] * 4)
    assert REPLAYED_ON != date.today(), "the replay date must differ from today"

    conn.execute(security_identifier.delete())
    conn.execute(security.delete())

    normalize_company_tickers(conn, landing_id)
    assert dates() == before


def test_explicit_as_of_overrides_the_landing_fetch_date(conn):
    """The override is retained for callers who know better than fetched_at."""
    landing_id = land_company_tickers(conn, _adapter(), now=REPLAYED_AT)
    normalize_company_tickers(conn, landing_id, as_of=AS_OF)
    row = conn.execute(
        select(security_identifier.c.valid_from).where(
            security_identifier.c.id_value == "AAPL"
        )
    ).scalar_one()
    assert row == AS_OF


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
