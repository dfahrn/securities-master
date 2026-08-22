"""One-off: land the exchange ticker file and every filer's submissions.

Separate from the CLI because it is a long-running Phase 2a bootstrap, not a
routine command. Safe to re-run: the exchange file is idempotent by content
hash, and the submissions loop resumes where it stopped.
"""

from datetime import datetime, timezone

from dotenv import load_dotenv

from securities_master.config import Settings
from securities_master.db import make_engine
from securities_master.ingest.edgar import EdgarAdapter
from securities_master.ingest.land import land_company_tickers_exchange
from securities_master.ingest.submissions import land_submissions
from securities_master.landing.tables import edgar_company_tickers_exchange
from sqlalchemy import select


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()
    engine = make_engine(settings)
    adapter = EdgarAdapter(user_agent=settings.sec_user_agent)
    run_started = datetime.now(timezone.utc)

    with engine.begin() as conn:
        landing_id = land_company_tickers_exchange(conn, adapter, now=run_started)
        print(f"exchange file: landing_id={landing_id}")
        if landing_id is None:
            landing_id = conn.execute(
                select(edgar_company_tickers_exchange.c.landing_id).order_by(
                    edgar_company_tickers_exchange.c.landing_id.desc()
                )
            ).scalars().first()
        payload = conn.execute(
            select(edgar_company_tickers_exchange.c.payload).where(
                edgar_company_tickers_exchange.c.landing_id == landing_id
            )
        ).scalar_one()

    ciks = sorted({f"{int(row[0]):010d}" for row in payload["data"]})
    print(f"distinct CIKs to fetch: {len(ciks)}")

    # Chunked so each batch COMMITS. One transaction spanning ~8,000 network
    # calls would hold a write transaction open for tens of minutes — the one
    # real run measured 41, against a 17-minute estimate, because sleeping
    # AFTER each fetch made the period `interval + latency` rather than
    # `interval`; deadline-based pacing now holds the nominal rate — and,
    # worse —
    # make the loop's resumability useless, because a crash would roll back
    # every fetch and the run-scoped skip would find nothing to skip.
    CHUNK = 200
    landed = unchanged = skipped = failed = 0
    failures: list[str] = []
    for start in range(0, len(ciks), CHUNK):
        batch = ciks[start : start + CHUNK]
        with engine.begin() as conn:
            result = land_submissions(conn, adapter, batch, run_started)
        landed += result.landed
        unchanged += result.unchanged
        skipped += result.skipped_this_run
        failed += result.failed
        failures.extend(result.failed_ciks)
        print(
            f"  {start + len(batch):>5}/{len(ciks)}  "
            f"landed={landed} unchanged={unchanged} failed={failed}"
        )

    print(
        f"landed={landed} unchanged={unchanged} "
        f"skipped_this_run={skipped} failed={failed}"
    )
    if failures:
        print(f"failed CIKs: {failures}")


if __name__ == "__main__":
    main()
