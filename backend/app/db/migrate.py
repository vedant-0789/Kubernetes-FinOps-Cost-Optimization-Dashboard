"""Programmatic access to Alembic so the API (dev) and tests can migrate
without shelling out. In production run `alembic upgrade head` as a job."""

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.attributes["configure_logger"] = False
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_head(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")
