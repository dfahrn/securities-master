from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, select

from securities_master.core.tables import security, security_identifier
from securities_master.landing.tables import edgar_company_tickers


@dataclass(frozen=True)
class NormalizeResult:
    created: int
    skipped_duplicate_cik: int


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


def normalize_company_tickers(
    conn: Connection, landing_id: int, as_of: date
) -> NormalizeResult:
    """Derive core.security and core.security_identifier from a landing row.

    CIK is the anchor identifier: SEC-assigned, permanent, never recycled.
    A company already known by CIK is skipped, which makes this idempotent.

    CIK identifies an issuer, not a security (e.g. Alphabet files under one
    CIK for both GOOGL and GOOG), and the EXCLUDE constraint on
    security_identifier forbids two securities sharing a CIK. Create-or-skip
    is therefore the only strategy this schema permits until Phase 2 adds an
    issuer table; rows beyond the first for a given CIK are counted in
    `skipped_duplicate_cik` rather than silently dropped, per the project's
    coverage-reporting principle.

    Known approximation: company_tickers.json is a snapshot with no history,
    so identifier ranges open at `as_of`. Phase 4 backfills earlier ranges
    from EDGAR former-names and Form 25 filings.
    """
    payload = conn.execute(
        select(edgar_company_tickers.c.payload).where(
            edgar_company_tickers.c.landing_id == landing_id
        )
    ).scalar_one()

    known = _existing_ciks(conn)
    created = 0
    skipped_duplicate_cik = 0

    for row in payload.values():
        cik = f"{int(row['cik_str']):010d}"
        if cik in known:
            skipped_duplicate_cik += 1
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

        conn.execute(
            security_identifier.insert(),
            [
                {
                    "security_id": security_id,
                    "id_type": "cik",
                    "id_value": cik,
                    "valid_from": as_of,
                    "valid_to": None,
                },
                {
                    "security_id": security_id,
                    "id_type": "ticker",
                    "id_value": str(row["ticker"]).upper(),
                    "valid_from": as_of,
                    "valid_to": None,
                },
            ],
        )
        known.add(cik)
        created += 1

    return NormalizeResult(created=created, skipped_duplicate_cik=skipped_duplicate_cik)
