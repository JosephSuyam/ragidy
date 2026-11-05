from logging.config import fileConfig
from typing import Any

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Tests pass their own URL through Config.attributes; everything else uses DATABASE_URL.
database_url: str = config.attributes.get("database_url") or get_settings().database_url
target_metadata = Base.metadata


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    # Tables without a model (pgvector store, LangGraph checkpoints) are owned elsewhere.
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_server_default=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
