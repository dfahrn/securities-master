from sqlalchemy import BigInteger, Column, DateTime, Identity, Table, Text, UniqueConstraint
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

edgar_company_tickers_exchange = Table(
    "edgar_company_tickers_exchange",
    metadata,
    Column("landing_id", BigInteger, Identity(), primary_key=True),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("payload_hash", Text, nullable=False, unique=True),
    Column("payload", JSONB, nullable=False),
    schema="landing",
)

edgar_submissions = Table(
    "edgar_submissions",
    metadata,
    Column("landing_id", BigInteger, Identity(), primary_key=True),
    Column("cik", Text, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("payload_hash", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    UniqueConstraint("cik", "payload_hash", name="edgar_submissions_cik_hash_key"),
    schema="landing",
)
