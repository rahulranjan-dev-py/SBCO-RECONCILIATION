"""Engine/session management and database initialization."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..paths import db_path
from .models import Base

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def init_db(path: Path | None = None) -> Engine:
    """Create (or open) the database, creating tables and seeds on first run."""
    global _engine, _session_factory
    target = path or db_path()
    _engine = create_engine(f"sqlite:///{target}", future=True)
    _configure_sqlite(_engine)
    Base.metadata.create_all(_engine)
    _session_factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)

    from .seed import seed_if_empty

    with _session_factory() as session:
        seed_if_empty(session)
        session.commit()
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialized; call init_db() first")
    return _engine


def get_session() -> Session:
    if _session_factory is None:
        raise RuntimeError("Database not initialized; call init_db() first")
    return _session_factory()
