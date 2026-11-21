"""Alembic environment: runs migrations online against app.db's engine."""

from logging.config import fileConfig

from alembic import context

from app.db import make_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    # lock_timeout: fail fast instead of queueing behind a long transaction.
    engine = make_engine(
        pool_size=1, max_overflow=0, connect_args={"options": "-c lock_timeout=10s"}
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not used in SurgeGate.")
run_migrations_online()
