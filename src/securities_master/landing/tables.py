from sqlalchemy import BigInteger, Column, DateTime, Identity, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

from securities_master.core.tables import metadata

edgar_company_tickers = Table(
    "edgar_company_tickers",
    metadata,
    Column("landing_id", BigInteger, Identity(), primary_key=True),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("payload_hash", Text, nullable=False, unique=True),
    Column("payload", JSONB, nullable=False),
    schema="landing",
)
