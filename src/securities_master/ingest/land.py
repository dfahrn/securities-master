from datetime import datetime

from sqlalchemy import Connection, select

from securities_master.ingest.base import payload_hash
from securities_master.ingest.edgar import EdgarAdapter
from securities_master.landing.tables import edgar_company_tickers


def land_company_tickers(
    conn: Connection, adapter: EdgarAdapter, now: datetime
) -> int | None:
    """Store the raw EDGAR ticker payload. Returns None if already present.

    Idempotency is by content hash, not timestamp: re-running against an
    unchanged upstream file must not create a second landing row.
    """
    payload = adapter.fetch_company_tickers_payload()
    digest = payload_hash(payload)

    existing = conn.execute(
        select(edgar_company_tickers.c.landing_id).where(
            edgar_company_tickers.c.payload_hash == digest
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    return conn.execute(
        edgar_company_tickers.insert()
        .values(fetched_at=now, payload_hash=digest, payload=payload)
        .returning(edgar_company_tickers.c.landing_id)
    ).scalar_one()
