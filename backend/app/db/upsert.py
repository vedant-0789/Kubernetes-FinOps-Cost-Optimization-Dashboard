"""Dialect-aware bulk INSERT ... ON CONFLICT for SQLite and PostgreSQL."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

# SQLite's bound-parameter limit is 32766; ~25 columns per sample row.
_CHUNK = 500
_BULK_CHUNK = 5000


def _insert_fn(session: Session):
    name = session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise NotImplementedError(f"Unsupported dialect: {name}")
    return insert


def insert_ignore(session: Session, model, rows: Sequence[dict]) -> int:
    """Insert rows, silently skipping primary-key conflicts. Returns rows inserted.

    Uses executemany with RETURNING (SQLAlchemy "insertmanyvalues"): the
    statement is compiled once and batched by the driver, and only rows that
    were actually inserted come back, so duplicates are counted exactly on
    both SQLite and PostgreSQL.
    """
    if not rows:
        return 0
    insert = _insert_fn(session)
    table = model.__table__
    pk = list(table.primary_key.columns)[0]
    # Core (not ORM) statement: the ORM bulk path splices RETURNING rows per
    # batch, which is quadratic for large inserts.
    stmt = insert(table).on_conflict_do_nothing().returning(pk)
    conn = session.connection()
    inserted = 0
    for i in range(0, len(rows), _BULK_CHUNK):
        inserted += len(conn.execute(stmt, list(rows[i:i + _BULK_CHUNK])).all())
    return inserted


def upsert(session: Session, model, rows: Sequence[dict], conflict_cols: Sequence[str],
           update_cols: Sequence[str]) -> None:
    if not rows:
        return
    # PostgreSQL rejects ON CONFLICT DO UPDATE touching the same row twice in
    # one statement, so collapse duplicate keys first (last occurrence wins).
    rows = list({tuple(r[c] for c in conflict_cols): r for r in rows}.values())
    insert = _insert_fn(session)
    for i in range(0, len(rows), _CHUNK):
        stmt = insert(model).values(list(rows[i:i + _CHUNK]))
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={c: getattr(stmt.excluded, c) for c in update_cols},
        )
        session.execute(stmt)
