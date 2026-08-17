from sqlalchemy import Engine, create_engine

from securities_master.config import Settings


def make_engine(settings: Settings) -> Engine:
    return create_engine(settings.database_url, future=True)
