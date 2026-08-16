from sqlalchemy import Column, MetaData, Table, Text

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
