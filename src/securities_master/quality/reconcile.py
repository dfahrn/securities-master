from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Connection, select, text

from securities_master.landing.tables import edgar_company_tickers_exchange


@dataclass(frozen=True)
class TickerDisagreement:
    cik: str
    only_in_exchange_file: tuple[str, ...]
    only_in_submissions: tuple[str, ...]


def ticker_disagreements(
    conn: Connection, landing_id: int
) -> list[TickerDisagreement]:
    """Where SEC's two endpoints contradict each other about a filer's tickers.

    Two SEC sources disagreeing is the vendor-reconciliation problem available
    without paying a vendor. Normalization reads the exchange file only; this
    measures what that choice costs rather than resolving it silently.

    A CIK with no landed submissions row is a coverage gap, not a
    contradiction, and is excluded.
    """
    payload = conn.execute(
        select(edgar_company_tickers_exchange.c.payload).where(
            edgar_company_tickers_exchange.c.landing_id == landing_id
        )
    ).scalar_one()

    from_file: dict[str, set[str]] = defaultdict(set)
    for row in payload["data"]:
        ticker = str(row[2] or "").strip().upper()
        if ticker:
            from_file[f"{int(row[0]):010d}"].add(ticker)

    stmt = text(
        """
        SELECT DISTINCT ON (cik) cik, payload->'tickers' AS tickers
        FROM landing.edgar_submissions
        ORDER BY cik, fetched_at DESC
        """
    )
    from_submissions: dict[str, set[str]] = {}
    for row in conn.execute(stmt):
        values = row.tickers or []
        from_submissions[row.cik] = {
            str(t).strip().upper() for t in values if str(t).strip()
        }

    disagreements = []
    for cik in sorted(set(from_file) & set(from_submissions)):
        file_only = from_file[cik] - from_submissions[cik]
        subs_only = from_submissions[cik] - from_file[cik]
        if file_only or subs_only:
            disagreements.append(
                TickerDisagreement(
                    cik=cik,
                    only_in_exchange_file=tuple(sorted(file_only)),
                    only_in_submissions=tuple(sorted(subs_only)),
                )
            )
    return disagreements
