from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, or_, select

from securities_master.core.tables import issuer, security, security_identifier


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


class DuplicateIdentifierError(Exception):
    """A security holds two identifiers of the same type on the same day."""


def identifiers_for(
    conn: Connection, security_id: int, as_of: date
) -> dict[str, str]:
    """All identifiers valid for a security on a date, keyed by id_type.

    Raises DuplicateIdentifierError if the security holds two identifiers of
    the same type on that date. The exclusion constraint keys on
    (id_type, id_value), not (security_id, id_type), so that state is
    representable — and returning one of the two arbitrarily is exactly the
    quiet wrongness this schema exists to prevent.
    """
    stmt = select(
        security_identifier.c.id_type, security_identifier.c.id_value
    ).where(
        security_identifier.c.security_id == security_id,
        *_valid_on(as_of),
    )
    identifiers: dict[str, str] = {}
    for row in conn.execute(stmt):
        if row.id_type in identifiers:
            raise DuplicateIdentifierError(
                f"security_id {security_id} has more than one "
                f"{row.id_type!r} identifier valid on {as_of}: "
                f"{identifiers[row.id_type]!r} and {row.id_value!r}"
            )
        identifiers[row.id_type] = row.id_value
    return identifiers


@dataclass(frozen=True)
class Issuer:
    issuer_id: int
    cik: str
    name: str
    entity_type: str | None
    sic_code: str | None
    sic_description: str | None


def issuer_for(conn: Connection, security_id: int) -> Issuer:
    """The issuer that owns a security.

    CIK identifies an issuer, not a security: Alphabet is one filer with two
    securities. This is the lookup that answers 'what else does this filer
    issue?' — the question Phase 1's 23% gap was really about.
    """
    stmt = (
        select(
            issuer.c.issuer_id,
            issuer.c.cik,
            issuer.c.name,
            issuer.c.entity_type,
            issuer.c.sic_code,
            issuer.c.sic_description,
        )
        .select_from(security.join(issuer, security.c.issuer_id == issuer.c.issuer_id))
        .where(security.c.security_id == security_id)
    )
    row = conn.execute(stmt).one_or_none()
    if row is None:
        raise LookupError(f"no security with security_id {security_id}")
    return Issuer(*row)
