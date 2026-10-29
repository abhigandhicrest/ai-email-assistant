"""SQLAlchemy engine and session management for MySQL."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when DATABASE_URL is missing or uses an unsupported driver."""


def build_engine(database_url: str) -> Engine:
    """Create an engine. The URL is validated and is not included in errors."""
    _require_mysql_url(database_url)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        connect_args={"connect_timeout": 5, "charset": "utf8mb4"},
        hide_parameters=True,
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_session() -> Iterator[Session]:
    """Yield a request session and commit only when the caller finishes cleanly."""
    with session_scope() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit a short unit of work. The database URL is not logged."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _require_mysql_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    if (
        parsed.scheme != "mysql+pymysql"
        or parsed.hostname is None
        or not database_name
    ):
        raise DatabaseConfigurationError(
            "DATABASE_URL must be a mysql+pymysql URL with a host and database name"
        )
