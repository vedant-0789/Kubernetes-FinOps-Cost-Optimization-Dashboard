"""Test fixtures.

Each test session gets a fresh database: a temp SQLite file by default, or the
PostgreSQL/TimescaleDB given in FINOPS_TEST_DATABASE_URL (used in CI) so the
same suite verifies both backends. Settings must be set before `app` imports.
"""

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="finops-test-")
os.environ["FINOPS_DATABASE_URL"] = os.environ.get(
    "FINOPS_TEST_DATABASE_URL", f"sqlite:///{_tmpdir}/test.db"
)
os.environ["FINOPS_ENVIRONMENT"] = "test"
os.environ["FINOPS_RUN_SCHEDULER_IN_API"] = "false"
os.environ["FINOPS_AUTO_MIGRATE"] = "true"
os.environ["FINOPS_SEED_DEMO_DATA"] = "true"
os.environ["FINOPS_DEMO_BACKFILL_DAYS"] = "2"
# Most tests exercise features, not auth; tests/test_auth.py switches it on.
os.environ["FINOPS_AUTH_REQUIRED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth_on(monkeypatch):
    """Turn real authentication on for one test."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)
