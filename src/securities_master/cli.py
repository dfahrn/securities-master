import sys

from dotenv import load_dotenv
from sqlalchemy import Connection, select

from securities_master.config import Settings
from securities_master.db import make_engine
from securities_master.landing.tables import edgar_company_tickers_exchange
from securities_master.normalize.exchange import (
    normalize_company_tickers_exchange,
)
from securities_master.quality.reconcile import ticker_disagreements


def latest_exchange_landing_id(conn: Connection) -> int | None:
    """The most recently landed exchange-file payload, or None."""
    return conn.execute(
        select(edgar_company_tickers_exchange.c.landing_id).order_by(
            edgar_company_tickers_exchange.c.landing_id.desc()
        )
    ).scalars().first()


def seed_phase2a() -> None:
    load_dotenv()
    engine = make_engine(Settings.from_env())

    with engine.begin() as conn:
        landing_id = latest_exchange_landing_id(conn)
        if landing_id is None:
            print(
                "No exchange payload landed. Run scripts/land_phase2a.py first.",
                file=sys.stderr,
            )
            return

        result = normalize_company_tickers_exchange(conn, landing_id)
        disagreements = ticker_disagreements(conn, landing_id)

    print(f"Normalized landing row {landing_id}:")
    print(f"  issuers created           {result.issuers_created}")
    print(f"  securities created        {result.securities_created}")
    print(f"  excluded (OTC)            {result.excluded_otc}")
    print(f"  excluded (no venue)       {result.excluded_no_exchange}")
    print(f"  excluded (unknown venue)  {result.excluded_unknown_venue}")
    print(f"  skipped (blank ticker)    {result.skipped_blank_ticker}")
    print(f"  issuers missing SEC facts {result.missing_submissions}")
    print(f"  CIKs where SEC's two sources disagree: {len(disagreements)}")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "seed-phase2a":
        print("usage: python -m securities_master.cli seed-phase2a", file=sys.stderr)
        return 2
    seed_phase2a()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
