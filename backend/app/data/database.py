"""SQLAlchemy engine and session helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings, get_settings


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create an engine with SQLite foreign-key enforcement."""
    url = database_url or get_settings().database_url
    parsed_url = make_url(url)
    if parsed_url.drivername.startswith("sqlite") and parsed_url.database not in {
        None,
        "",
        ":memory:",
    }:
        Path(parsed_url.database).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
            del connection_record
            if not isinstance(dbapi_connection, SQLiteConnection):
                raise TypeError("SQLite URL produced a non-SQLite connection")
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a typed session factory bound to one engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit or roll back one unit of work."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def engine_from_settings(settings: Settings) -> Engine:
    """Create the configured engine without consulting global state."""
    return create_database_engine(settings.database_url)
