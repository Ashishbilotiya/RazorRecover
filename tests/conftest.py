"""Shared pytest fixtures for RazorRecover.

The test suite runs against an in-memory SQLite database — Postgres is not
required to execute the suite, but the production code path is identical
because we route everything through SQLAlchemy.
"""

from __future__ import annotations

import os

# Configure environment BEFORE importing anything from the app so that
# `Settings()` reads the right test values.
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_ENV", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.audit import logger as audit_logger
from backend.db import database as db_module
from backend.db.database import Base, configure_engine, get_db, reset_for_tests
from backend.main import app


@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset engine + create a fresh schema for every test."""
    reset_for_tests()
    engine = configure_engine("sqlite:///:memory:")
    # Import models so they register against Base.metadata.
    from backend.db import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def session(_fresh_db):
    """Yield a raw SQLAlchemy session bound to the test DB."""
    SessionLocal = db_module.get_session_factory()
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client(_fresh_db):
    """FastAPI TestClient with the DB session dependency overridden."""

    SessionLocal = db_module.get_session_factory()

    def _override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def webhook_secret() -> str:
    return "test_webhook_secret"


def sign(body: bytes, secret: str) -> str:
    """Generate a valid Razorpay-style HMAC-SHA256 hex signature for tests."""
    import hashlib
    import hmac

    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def signer(webhook_secret):
    def _sign(body: bytes) -> str:
        return sign(body, webhook_secret)

    return _sign


__all__ = [
    "audit_logger",
    "client",
    "session",
    "sign",
    "signer",
    "webhook_secret",
]
