from datetime import date

from sqlalchemy import Connection, or_, select

from securities_master.core.tables import security_identifier


def _valid_on(as_of: date):
    """Half-open range predicate: [valid_from, valid_to)."""
    return (
        security_identifier.c.valid_from <= as_of,
        or_(
            security_identifier.c.valid_to.is_(None),
            security_identifier.c.valid_to > as_of,
        ),
    )


def resolve(conn: Connection, ticker: str, as_of: date) -> int | None:
    """Map a ticker to a security_id as of a date.

    Returns None when the ticker was unassigned then. Tickers are recycled
    to unrelated companies, so resolution without a date is meaningless.
    """
    stmt = select(security_identifier.c.security_id).where(
        security_identifier.c.id_type == "ticker",
        security_identifier.c.id_value == ticker.upper(),
        *_valid_on(as_of),
    )
    return conn.execute(stmt).scalar_one_or_none()


def identifiers_for(
    conn: Connection, security_id: int, as_of: date
) -> dict[str, str]:
    """All identifiers valid for a security on a date, keyed by id_type."""
    stmt = select(
        security_identifier.c.id_type, security_identifier.c.id_value
    ).where(
        security_identifier.c.security_id == security_id,
        *_valid_on(as_of),
    )
    return {row.id_type: row.id_value for row in conn.execute(stmt)}
