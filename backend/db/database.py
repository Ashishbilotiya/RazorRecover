"""SQLAlchemy engine, session factory, and declarative base.

Settings are read from environment variables via pydantic-settings.
Never hard-code credentials.

See CLAUDE.md sections 10, 38.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/razorrecover",
        description="SQLAlchemy database URL.",
    )
    razorpay_key_id: str = Field(default="", description="Razorpay public key id.")
    razorpay_key_secret: str = Field(default="", description="Razorpay secret key.")
    razorpay_webhook_secret: str = Field(
        default="", description="Razorpay webhook signing secret."
    )

    app_env: str = Field(default="development", description="development | test | production")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_settings: Settings | None = None
_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_settings() -> Settings:
    """Cached settings accessor."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _build_engine(url: str) -> Engine:
    """Create a SQLAlchemy engine.

    PostgreSQL gets psycopg2 connection-pooling; SQLite (used by tests) needs
    ``check_same_thread=False`` plus a ``StaticPool`` so that multiple sessions
    share the same connection — required for in-memory SQLite which is
    per-connection by default.
    """
    parsed = urlsplit(url)
    is_sqlite = parsed.scheme.startswith("sqlite")
    if is_sqlite:
        from sqlalchemy.pool import StaticPool

        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    return create_engine(url, pool_pre_ping=True, future=True)


def configure_engine(url: str | None = None) -> Engine:
    """Initialize the global engine + session factory.

    `url=None` re-reads settings; pass an explicit URL to point tests at sqlite.
    """
    global _engine, _SessionFactory
    target = url if url is not None else get_settings().database_url
    _engine = _build_engine(target)
    _SessionFactory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _SessionFactory is None:
        configure_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped Session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Used at app startup; replaced by Alembic in Phase 2+."""
    from backend.db import models  # noqa: F401 — register mappers

    Base.metadata.create_all(bind=get_engine())


def reset_for_tests() -> None:
    """Drop cached engine/factory — used by the test suite."""
    global _engine, _SessionFactory, _settings
    _engine = None
    _SessionFactory = None
    _settings = None


# Exposed for callers that want to introspect the connection target.
def describe_database_url(url: str) -> dict[str, str]:
    """Return a redacted dict describing the URL — useful for audit logs."""
    parsed = urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname or "",
        "port": str(parsed.port or ""),
        "database": parsed.path.lstrip("/"),
        "query": urlencode(parse_qsl(parsed.query)),
    }


__all__ = [
    "Base",
    "Settings",
    "URL",
    "configure_engine",
    "describe_database_url",
    "get_db",
    "get_engine",
    "get_session_factory",
    "get_settings",
    "init_db",
    "reset_for_tests",
]
