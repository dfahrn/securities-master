from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, select, text

from securities_master.core.tables import (
    issuer,
    security,
    security_identifier,
    security_listing,
)
from securities_master.landing.tables import edgar_company_tickers_exchange

EXCHANGE_MIC = {"Nasdaq": "XNAS", "NYSE": "XNYS", "CBOE": "BATS"}


@dataclass(frozen=True)
class ExchangeNormalizeResult:
    issuers_created: int
    securities_created: int
    excluded_otc: int
    excluded_no_exchange: int
    excluded_unknown_venue: int
    skipped_blank_ticker: int
    missing_submissions: int


def _clean_ticker(raw: object) -> str:
    if raw is None:
        return ""
    return str(raw).strip().upper()


def _blank_to_none(value: object) -> str | None:
    """SEC sends '' for filers with no SIC. An empty string is not a code."""
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _submissions_facts(conn: Connection) -> dict[str, tuple]:
    """Latest landed submissions facts per CIK.

    DISTINCT ON takes the most recently fetched payload for each filer, so a
    re-run that landed fresher data wins without deleting the older rows.
    """
    stmt = text(
        """
        SELECT DISTINCT ON (cik)
               cik,
               payload->>'entityType'     AS entity_type,
               payload->>'sic'            AS sic_code,
               payload->>'sicDescription' AS sic_description
        FROM landing.edgar_submissions
        ORDER BY cik, fetched_at DESC
        """
    )
    return {
        row.cik: (row.entity_type, row.sic_code, row.sic_description)
        for row in conn.execute(stmt)
    }


def normalize_company_tickers_exchange(
    conn: Connection, landing_id: int, as_of: date | None = None
) -> ExchangeNormalizeResult:
    """Derive issuer, security, identifier, and listing rows from the exchange file.

    One `issuer` per CIK, one `security` per (CIK, ticker) row. This is what
    closes Phase 1's 23% gap: CIK identifies an issuer, not a security, so
    Alphabet becomes one issuer owning both GOOGL and GOOG.

    `as_of` defaults to the landing row's own `fetched_at` date, which is what
    makes `core` reproducible from `landing` (principle P4): replaying this
    landing row a year from now writes the same dates it wrote the first time.

    OTC and null-venue rows are excluded and counted (D4). An issuer is created
    only for a CIK with at least one included security, so a filer appearing
    solely on excluded rows produces nothing. When a CIK has no landed
    submissions payload the SEC-derived columns stay NULL and the security's
    type is `unknown` — a missing fact is recorded as missing, never guessed.
    """
    payload, fetched_at = conn.execute(
        select(
            edgar_company_tickers_exchange.c.payload,
            edgar_company_tickers_exchange.c.fetched_at,
        ).where(edgar_company_tickers_exchange.c.landing_id == landing_id)
    ).one()
    if as_of is None:
        as_of = fetched_at.date()

    facts = _submissions_facts(conn)

    issuers_created = securities_created = 0
    excluded_otc = excluded_no_exchange = excluded_unknown_venue = 0
    skipped_blank_ticker = 0
    missing_ciks: set[str] = set()
    issuer_ids: dict[str, int] = {}

    for row in payload["data"]:
        raw_cik, name, raw_ticker, venue = row[0], row[1], row[2], row[3]
        cik = f"{int(raw_cik):010d}"

        if venue is None:
            excluded_no_exchange += 1
            continue
        if venue == "OTC":
            excluded_otc += 1
            continue
        if venue not in EXCHANGE_MIC:
            excluded_unknown_venue += 1
            continue

        if cik not in issuer_ids:
            entity_type, sic_code, sic_description = facts.get(cik, (None, None, None))
            if cik not in facts:
                missing_ciks.add(cik)
            issuer_ids[cik] = conn.execute(
                issuer.insert()
                .values(
                    cik=cik,
                    name=str(name),
                    entity_type=_blank_to_none(entity_type),
                    sic_code=_blank_to_none(sic_code),
                    sic_description=_blank_to_none(sic_description),
                )
                .returning(issuer.c.issuer_id)
            ).scalar_one()
            issuers_created += 1

        entity_type = facts.get(cik, (None, None, None))[0]
        security_type = "common_stock" if entity_type == "operating" else "unknown"

        security_id = conn.execute(
            security.insert()
            .values(
                issuer_id=issuer_ids[cik],
                security_type=security_type,
                status="active",
                first_seen_date=as_of,
            )
            .returning(security.c.security_id)
        ).scalar_one()
        securities_created += 1

        ticker = _clean_ticker(raw_ticker)
        if ticker:
            conn.execute(
                security_identifier.insert().values(
                    security_id=security_id,
                    id_type="ticker",
                    id_value=ticker,
                    valid_from=as_of,
                    valid_to=None,
                )
            )
        else:
            # A malformed ticker must cost us one identifier, never the
            # security and never the transaction.
            skipped_blank_ticker += 1

        conn.execute(
            security_listing.insert().values(
                security_id=security_id,
                exchange_mic=EXCHANGE_MIC[venue],
                valid_from=as_of,
                valid_to=None,
                delisting_reason=None,
            )
        )

    return ExchangeNormalizeResult(
        issuers_created=issuers_created,
        securities_created=securities_created,
        excluded_otc=excluded_otc,
        excluded_no_exchange=excluded_no_exchange,
        excluded_unknown_venue=excluded_unknown_venue,
        skipped_blank_ticker=skipped_blank_ticker,
        missing_submissions=len(missing_ciks),
    )
