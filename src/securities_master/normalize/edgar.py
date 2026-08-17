from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, select

from securities_master.core.tables import security, security_identifier
from securities_master.landing.tables import edgar_company_tickers


@dataclass(frozen=True)
class NormalizeResult:
    created: int
    skipped_duplicate_cik: int
    skipped_cik_ticker_changed: int
    skipped_blank_ticker: int


def _existing_ciks(conn: Connection) -> set[str]:
    return set(
        conn.execute(
            select(security_identifier.c.id_value).where(
                security_identifier.c.id_type == "cik"
            )
        )
        .scalars()
        .all()
    )


def _tickers_by_cik(conn: Connection) -> dict[str, set[str]]:
    """Tickers currently recorded in core, grouped by the security's CIK.

    Used to tell a share class this schema cannot represent apart from a
    ticker rename that was dropped on the floor: both hit the skip branch,
    but only one of them leaves `resolve()` wrong about today.
    """
    cik = security_identifier.alias("cik")
    ticker = security_identifier.alias("ticker")
    stmt = (
        select(cik.c.id_value, ticker.c.id_value)
        .select_from(cik.join(ticker, cik.c.security_id == ticker.c.security_id))
        .where(cik.c.id_type == "cik", ticker.c.id_type == "ticker")
    )
    grouped: dict[str, set[str]] = defaultdict(set)
    for cik_value, ticker_value in conn.execute(stmt):
        grouped[cik_value].add(ticker_value)
    return grouped


def _clean_ticker(raw: object) -> str:
    """Normalize a payload ticker, returning '' when it is unusable."""
    if raw is None:
        return ""
    return str(raw).strip().upper()


def normalize_company_tickers(
    conn: Connection, landing_id: int, as_of: date | None = None
) -> NormalizeResult:
    """Derive core.security and core.security_identifier from a landing row.

    CIK is the anchor identifier: SEC-assigned, permanent, never recycled.
    A company already known by CIK is skipped, which makes this idempotent.

    `as_of` defaults to the landing row's own `fetched_at` date, which is what
    makes `core` reproducible from `landing` (principle P4): replaying this
    landing row a year from now writes the same `valid_from` and
    `first_seen_date` it wrote the first time, because the date comes from the
    stored payload's provenance rather than from the wall clock. Callers may
    still pass `as_of` explicitly to override it.

    CIK identifies an issuer, not a security (e.g. Alphabet files under one
    CIK for both GOOGL and GOOG), and the EXCLUDE constraint on
    security_identifier forbids two securities sharing a CIK. Create-or-skip
    is therefore the only strategy this schema permits until Phase 2 adds an
    issuer table. Skips are split into two counters rather than conflated:

    - `skipped_duplicate_cik`: a share class this schema cannot represent, or
      a row already ingested. `resolve()` is wrong about nothing; the ticker
      is simply absent.
    - `skipped_cik_ticker_changed`: the CIK's recorded ticker no longer
      appears in the payload for that CIK, i.e. the issuer renamed its
      ticker. The new ticker is not created and the stale range stays
      open-ended, so `resolve()` is wrong about *today* until Phase 4 adds
      range close-out logic. Counted separately so that gap is measurable.

    Known approximation: company_tickers.json is a snapshot with no history,
    so identifier ranges open at `as_of`. Phase 4 backfills earlier ranges
    from EDGAR former-names and Form 25 filings.
    """
    payload, fetched_at = conn.execute(
        select(
            edgar_company_tickers.c.payload, edgar_company_tickers.c.fetched_at
        ).where(edgar_company_tickers.c.landing_id == landing_id)
    ).one()
    if as_of is None:
        as_of = fetched_at.date()

    known = _existing_ciks(conn)
    recorded_tickers = _tickers_by_cik(conn)

    payload_tickers: dict[str, set[str]] = defaultdict(set)
    for row in payload.values():
        payload_ticker = _clean_ticker(row["ticker"])
        if payload_ticker:
            payload_tickers[f"{int(row['cik_str']):010d}"].add(payload_ticker)

    created = 0
    skipped_duplicate_cik = 0
    skipped_cik_ticker_changed = 0
    skipped_blank_ticker = 0

    for row in payload.values():
        cik = f"{int(row['cik_str']):010d}"
        ticker = _clean_ticker(row["ticker"])

        if cik in known:
            recorded = recorded_tickers.get(cik, set())
            if not recorded or ticker in recorded or recorded & payload_tickers[cik]:
                # Either this exact assignment is already ingested, or the
                # CIK's recorded ticker is still in the payload and this row
                # is an additional share class. A CIK with no recorded ticker
                # at all cannot have been renamed.
                skipped_duplicate_cik += 1
            else:
                # The recorded ticker vanished from the payload: a rename we
                # cannot apply without close-out logic.
                skipped_cik_ticker_changed += 1
            continue

        security_id = conn.execute(
            security.insert()
            .values(
                security_type="common_stock",
                status="active",
                first_seen_date=as_of,
            )
            .returning(security.c.security_id)
        ).scalar_one()

        identifiers = [
            {
                "security_id": security_id,
                "id_type": "cik",
                "id_value": cik,
                "valid_from": as_of,
                "valid_to": None,
            }
        ]
        if ticker:
            identifiers.append(
                {
                    "security_id": security_id,
                    "id_type": "ticker",
                    "id_value": ticker,
                    "valid_from": as_of,
                    "valid_to": None,
                }
            )
            recorded_tickers[cik].add(ticker)
        else:
            # A malformed ticker must not cost us the whole transaction, and
            # must not cost us the issuer either: the security and its CIK
            # anchor are still worth more than the one unusable identifier.
            skipped_blank_ticker += 1

        conn.execute(security_identifier.insert(), identifiers)
        known.add(cik)
        created += 1

    return NormalizeResult(
        created=created,
        skipped_duplicate_cik=skipped_duplicate_cik,
        skipped_cik_ticker_changed=skipped_cik_ticker_changed,
        skipped_blank_ticker=skipped_blank_ticker,
    )
