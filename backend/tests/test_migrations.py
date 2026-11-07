from alembic import command
from sqlalchemy import create_engine, inspect

from app.db.migrate import alembic_config


def test_migrations_upgrade_and_downgrade_cleanly(tmp_path):
    url = f"sqlite:///{tmp_path}/mig.db"
    cfg = alembic_config(url)

    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"metrics_snapshots", "zombie_workloads", "recommendations", "action_logs",
            "system_settings"} <= tables

    command.downgrade(cfg, "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
