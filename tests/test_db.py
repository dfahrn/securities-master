import os

import pytest
from sqlalchemy import text

from securities_master.config import Settings
from securities_master.db import make_engine


@pytest.fixture
def engine():
    settings = Settings(
        database_url=os.environ["TEST_DATABASE_URL"],
        sec_user_agent="test test@example.com",
    )
    return make_engine(settings)


def test_engine_connects(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_schemas_exist(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name IN ('landing', 'core')"
            )
        ).scalars().all()
    assert set(rows) == {"landing", "core"}


def test_btree_gist_installed(engine):
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
        ).scalar_one()
    assert count == 1
