from datetime import datetime, timezone

from securities_master.landing.tables import (
    edgar_company_tickers_exchange,
    edgar_submissions,
)
from securities_master.quality.reconcile import ticker_disagreements

FETCHED = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _land(conn, rows):
    return conn.execute(
        edgar_company_tickers_exchange.insert()
        .values(
            fetched_at=FETCHED,
            payload_hash="h1",
            payload={"fields": ["cik", "name", "ticker", "exchange"], "data": rows},
        )
        .returning(edgar_company_tickers_exchange.c.landing_id)
    ).scalar_one()


def _land_submissions(conn, cik_int, tickers):
    conn.execute(
        edgar_submissions.insert().values(
            cik=f"{cik_int:010d}",
            fetched_at=FETCHED,
            payload_hash=f"s{cik_int}",
            payload={"tickers": tickers},
        )
    )


def test_agreeing_sources_report_nothing(conn):
    landing_id = _land(conn, [[320193, "Apple Inc.", "AAPL", "Nasdaq"]])
    _land_submissions(conn, 320193, ["AAPL"])
    assert ticker_disagreements(conn, landing_id) == []


def test_reports_tickers_only_submissions_knows(conn):
    """Alphabet's real case: submissions lists GOOGM/GOOGN, the file does not."""
    landing_id = _land(
        conn,
        [
            [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"],
            [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
        ],
    )
    _land_submissions(conn, 1652044, ["GOOGL", "GOOG", "GOOGM", "GOOGN"])
    [found] = ticker_disagreements(conn, landing_id)
    assert found.cik == "0001652044"
    assert found.only_in_submissions == ("GOOGM", "GOOGN")
    assert found.only_in_exchange_file == ()


def test_reports_tickers_only_the_file_knows(conn):
    landing_id = _land(conn, [[111, "Split Brain Co", "SBC", "NYSE"]])
    _land_submissions(conn, 111, [])
    [found] = ticker_disagreements(conn, landing_id)
    assert found.only_in_exchange_file == ("SBC",)
    assert found.only_in_submissions == ()


def test_a_cik_with_no_submissions_row_is_not_a_disagreement(conn):
    """Missing data is a coverage gap, not a contradiction."""
    landing_id = _land(conn, [[111, "Unfetched Co", "UNF", "NYSE"]])
    assert ticker_disagreements(conn, landing_id) == []
