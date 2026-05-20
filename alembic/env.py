"""
Alembic environment configuration for async SQLAlchemy + asyncpg.

Uses the application's ``Base.metadata`` so that ``--autogenerate`` can
diff the ORM models against the live database.  The connection URL is
pulled from ``settings.database_url`` at runtime to ensure consistency
with the rest of the application.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.config import settings
from src.models.memory import Base

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values.
# ---------------------------------------------------------------------------

config = context.config

# Override the sqlalchemy.url from alembic.ini with the application setting.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object used for autogenerate support.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline (SQL-script) migrations
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.  Useful for
    review or applying to a managed database where direct connections are
    not allowed.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online (async) migrations
# ---------------------------------------------------------------------------

def do_run_migrations(connection) -> None:
    """Configure the Alembic context with an active connection and run."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine, connect, and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an async engine."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
