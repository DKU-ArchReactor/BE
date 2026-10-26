"""Apply PostgreSQL migrations once at a time before starting each container."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import settings

MIGRATION_LOCK_ID = 7281946301


def migrate() -> None:
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"connect_timeout": 10},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL lock_timeout = '120s'"))
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": MIGRATION_LOCK_ID},
            )
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        # Commit and release the lock only after the migration completes.
    finally:
        engine.dispose()


if __name__ == "__main__":
    migrate()
