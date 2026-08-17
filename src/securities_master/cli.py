import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from securities_master.config import Settings
from securities_master.db import make_engine
from securities_master.ingest.edgar import EdgarAdapter
from securities_master.ingest.land import land_company_tickers
from securities_master.normalize.edgar import normalize_company_tickers


def seed_edgar() -> None:
    load_dotenv()
    settings = Settings.from_env()
    engine = make_engine(settings)
    adapter = EdgarAdapter(user_agent=settings.sec_user_agent)
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        landing_id = land_company_tickers(conn, adapter, now=now)
        if landing_id is None:
            print("EDGAR payload unchanged; nothing landed.")
            return
        # No `as_of`: it defaults to the landing row's `fetched_at` date, so a
        # replay of this landing row reproduces these rows rather than
        # rebuilding them with a fresh wall-clock date.
        result = normalize_company_tickers(conn, landing_id)
        print(
            f"Landed row {landing_id}; created {result.created} securities; "
            f"skipped {result.skipped_duplicate_cik} duplicate-CIK share classes; "
            f"skipped {result.skipped_cik_ticker_changed} changed tickers on a "
            f"known CIK; skipped {result.skipped_blank_ticker} blank tickers."
        )


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "seed-edgar":
        print("usage: python -m securities_master.cli seed-edgar", file=sys.stderr)
        return 2
    seed_edgar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
