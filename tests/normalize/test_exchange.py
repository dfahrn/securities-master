from datetime import date, datetime, timezone

from sqlalchemy import func, select

from securities_master.core.identity import resolve
from securities_master.core.tables import (
    issuer,
    security,
    security_identifier,
    security_listing,
)
from securities_master.landing.tables import (
    edgar_company_tickers_exchange,
    edgar_submissions,
)
from securities_master.normalize.exchange import normalize_company_tickers_exchange

FETCHED = datetime(2020, 3, 1, 14, 30, tzinfo=timezone.utc)
FETCHED_DATE = date(2020, 3, 1)

ROWS = [
    [320193, "Apple Inc.", "AAPL", "Nasdaq"],
    [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
    [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
    [884394, "SPDR S&P 500 ETF TRUST", "SPY", "NYSE"],
    [111, "Cboe Listed Co", "CBOEX", "CBOE"],
    [222, "Shell Co", "SHLL", "OTC"],
    [333, "Venueless Co", "NOVEN", None],
]


def _land(conn, rows=None):
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": rows if rows is not None else ROWS,
    }
    return conn.execute(
        edgar_company_tickers_exchange.insert()
        .values(fetched_at=FETCHED, payload_hash="h1", payload=payload)
        .returning(edgar_company_tickers_exchange.c.landing_id)
    ).scalar_one()


def _land_submissions(conn, facts):
    """facts: {cik_int: (entityType, sic, sicDescription)}"""
    for cik_int, (etype, sic, sic_desc) in facts.items():
        conn.execute(
            edgar_submissions.insert().values(
                cik=f"{cik_int:010d}",
                fetched_at=FETCHED,
                payload_hash=f"s{cik_int}",
                payload={
                    "entityType": etype,
                    "sic": sic,
                    "sicDescription": sic_desc,
                },
            )
        )


ALL_FACTS = {
    320193: ("operating", "3571", "Electronic Computers"),
    1652044: ("operating", "7370", "Services-Computer Programming"),
    884394: ("other", "", ""),
    111: ("operating", "6199", "Finance Services"),
}


def test_one_issuer_owns_two_securities(conn):
    """Alphabet: the case the whole phase exists for."""
    _land_submissions(conn, ALL_FACTS)
    result = normalize_company_tickers_exchange(conn, _land(conn))
    issuer_id = conn.execute(
        select(issuer.c.issuer_id).where(issuer.c.cik == "0001652044")
    ).scalar_one()
    owned = conn.execute(
        select(security.c.security_id).where(security.c.issuer_id == issuer_id)
    ).scalars().all()
    assert len(owned) == 2
    assert result.securities_created == 5


def test_both_alphabet_tickers_resolve(conn):
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    googl = resolve(conn, "GOOGL", FETCHED_DATE)
    goog = resolve(conn, "GOOG", FETCHED_DATE)
    assert googl is not None and goog is not None
    assert googl != goog


def test_otc_and_null_venues_are_excluded_and_counted(conn):
    _land_submissions(conn, ALL_FACTS)
    result = normalize_company_tickers_exchange(conn, _land(conn))
    assert result.excluded_otc == 1
    assert result.excluded_no_exchange == 1
    assert resolve(conn, "SHLL", FETCHED_DATE) is None
    assert resolve(conn, "NOVEN", FETCHED_DATE) is None


def test_an_issuer_is_not_created_for_excluded_only_ciks(conn):
    """A filer appearing solely on excluded rows produces no issuer."""
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    for excluded_cik in ("0000000222", "0000000333"):
        found = conn.execute(
            select(issuer.c.issuer_id).where(issuer.c.cik == excluded_cik)
        ).scalar_one_or_none()
        assert found is None


def test_entity_type_drives_security_type(conn):
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    apple = resolve(conn, "AAPL", FETCHED_DATE)
    spy = resolve(conn, "SPY", FETCHED_DATE)
    types = dict(
        conn.execute(
            select(security.c.security_id, security.c.security_type).where(
                security.c.security_id.in_([apple, spy])
            )
        ).all()
    )
    assert types[apple] == "common_stock"
    assert types[spy] == "unknown"


def test_a_missing_submissions_payload_yields_nulls_and_unknown(conn):
    """A failed fetch records a missing fact, never a guessed one."""
    _land_submissions(conn, {k: v for k, v in ALL_FACTS.items() if k != 320193})
    result = normalize_company_tickers_exchange(conn, _land(conn))
    assert result.missing_submissions == 1
    apple_issuer = conn.execute(
        select(issuer.c.entity_type, issuer.c.sic_code).where(
            issuer.c.cik == "0000320193"
        )
    ).one()
    assert apple_issuer.entity_type is None
    assert apple_issuer.sic_code is None
    apple = resolve(conn, "AAPL", FETCHED_DATE)
    stype = conn.execute(
        select(security.c.security_type).where(security.c.security_id == apple)
    ).scalar_one()
    assert stype == "unknown"


def test_empty_sic_is_stored_as_null(conn):
    """SEC sends '' for filers with no SIC; an empty string is not a code."""
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    row = conn.execute(
        select(issuer.c.sic_code, issuer.c.sic_description).where(
            issuer.c.cik == "0000884394"
        )
    ).one()
    assert row.sic_code is None
    assert row.sic_description is None


def test_listings_carry_the_mapped_mic(conn):
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    apple = resolve(conn, "AAPL", FETCHED_DATE)
    cboe = resolve(conn, "CBOEX", FETCHED_DATE)
    mics = dict(
        conn.execute(
            select(security_listing.c.security_id, security_listing.c.exchange_mic)
        ).all()
    )
    assert mics[apple] == "XNAS"
    assert mics[cboe] == "BATS"


def test_listing_ranges_open_at_the_landing_fetch_date(conn):
    _land_submissions(conn, ALL_FACTS)
    normalize_company_tickers_exchange(conn, _land(conn))
    row = conn.execute(
        select(security_listing.c.valid_from, security_listing.c.valid_to)
    ).first()
    assert row.valid_from == FETCHED_DATE
    assert row.valid_to is None


def test_a_blank_ticker_keeps_the_security_and_is_counted(conn):
    _land_submissions(conn, {320193: ALL_FACTS[320193]})
    landing_id = _land(conn, [[320193, "Apple Inc.", "   ", "Nasdaq"]])
    result = normalize_company_tickers_exchange(conn, landing_id)
    assert result.skipped_blank_ticker == 1
    assert result.securities_created == 1
    tickers = conn.execute(
        select(func.count()).select_from(security_identifier)
    ).scalar_one()
    assert tickers == 0


def test_normalize_replays_identically_from_landing(conn):
    """P4: a rebuild reproduces, it does not merely rebuild."""
    _land_submissions(conn, ALL_FACTS)
    landing_id = _land(conn)
    normalize_company_tickers_exchange(conn, landing_id)
    before = conn.execute(
        select(security.c.first_seen_date).order_by(security.c.security_id)
    ).scalars().all()
    assert before == [FETCHED_DATE] * 5
    assert FETCHED_DATE != date.today()

    conn.execute(security_listing.delete())
    conn.execute(security_identifier.delete())
    conn.execute(security.delete())
    conn.execute(issuer.delete())

    normalize_company_tickers_exchange(conn, landing_id)
    after = conn.execute(
        select(security.c.first_seen_date).order_by(security.c.security_id)
    ).scalars().all()
    assert after == before


def test_explicit_as_of_overrides_the_landing_fetch_date(conn):
    _land_submissions(conn, ALL_FACTS)
    override = date(2021, 7, 4)
    normalize_company_tickers_exchange(conn, _land(conn), as_of=override)
    seen = conn.execute(select(security.c.first_seen_date)).scalars().first()
    assert seen == override
