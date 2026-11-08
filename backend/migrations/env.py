from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

import app.db.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.db.database import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# An explicit URL (e.g. from tests) wins over the environment.
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", url)
target_metadata = Base.metadata
MIGRATION_LOCK_KEY = 7_241_993_001  # arbitrary, constant across releases


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        is_pg = connection.dialect.name == "postgresql"
        if is_pg:
            # Several API pods may start at once (each runs migrations in an
            # init container); a session-level advisory lock serialises them.
            connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            connection.commit()
        try:
            context.configure(connection=connection, target_metadata=target_metadata,
                              render_as_batch=url.startswith("sqlite"), compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_pg:
                connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
                connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
