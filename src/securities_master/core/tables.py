from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    ForeignKey,
    Identity,
    MetaData,
    Table,
    Text,
)

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

SECURITY_TYPES = ("common_stock", "etf", "adr", "unknown")
SECURITY_STATUSES = ("active", "delisted")

issuer = Table(
    "issuer",
    metadata,
    Column("issuer_id", BigInteger, Identity(), primary_key=True),
    Column("cik", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("entity_type", Text, nullable=True),
    Column("sic_code", Text, nullable=True),
    Column("sic_description", Text, nullable=True),
    schema="core",
)

security = Table(
    "security",
    metadata,
    Column("security_id", BigInteger, Identity(), primary_key=True),
    Column(
        "issuer_id",
        BigInteger,
        ForeignKey("core.issuer.issuer_id"),
        nullable=False,
    ),
    Column("security_type", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("first_seen_date", Date, nullable=False),
    schema="core",
)

IDENTIFIER_TYPES = ("ticker", "cusip", "isin", "figi")

security_identifier = Table(
    "security_identifier",
    metadata,
    Column("security_identifier_id", BigInteger, Identity(), primary_key=True),
    Column(
        "security_id",
        BigInteger,
        ForeignKey("core.security.security_id"),
        nullable=False,
    ),
    Column("id_type", Text, nullable=False),
    Column("id_value", Text, nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=True),
    schema="core",
)

security_listing = Table(
    "security_listing",
    metadata,
    Column("security_listing_id", BigInteger, Identity(), primary_key=True),
    Column(
        "security_id",
        BigInteger,
        ForeignKey("core.security.security_id"),
        nullable=False,
    ),
    Column("exchange_mic", Text, ForeignKey("core.exchange.mic"), nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=True),
    Column("delisting_reason", Text, nullable=True),
    schema="core",
)
