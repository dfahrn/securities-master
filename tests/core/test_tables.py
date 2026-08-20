from sqlalchemy import select

from securities_master.core.tables import exchange


def test_exchange_seeded_with_us_mics(conn):
    rows = conn.execute(select(exchange.c.mic).order_by(exchange.c.mic)).scalars().all()
    assert rows == ["BATS", "XNAS", "XNYS"]


def test_exchange_carries_timezone(conn):
    tz = conn.execute(
        select(exchange.c.timezone).where(exchange.c.mic == "XNYS")
    ).scalar_one()
    assert tz == "America/New_York"
