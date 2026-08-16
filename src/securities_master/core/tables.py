from sqlalchemy import BigInteger, Column, Date, Identity, MetaData, Table, Text

metadata = MetaData()

exchange = Table(
    "exchange",
    metadata,
    Column("mic", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("country", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    schema="core",
)

SECURITY_TYPES = ("common_stock", "etf", "adr")
SECURITY_STATUSES = ("active", "delisted")

security = Table(
    "security",
    metadata,
    Column("security_id", BigInteger, Identity(), primary_key=True),
    Column("security_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("first_seen_date", Date, nullable=False),
    schema="core",
)
