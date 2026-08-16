import os

import pytest
from dotenv import load_dotenv

from securities_master.config import Settings
from securities_master.db import make_engine

load_dotenv()


@pytest.fixture(scope="session")
def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; see .env.example")
    return make_engine(
        Settings(database_url=url, sec_user_agent="test test@example.com")
    )


@pytest.fixture
def conn(engine):
    """A connection inside a transaction that is always rolled back.

    Every test therefore sees a clean database without truncating tables.
    """
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
