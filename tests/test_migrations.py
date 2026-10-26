"""Run only against an explicitly supplied disposable PostgreSQL database."""

import os
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app import migrate


@pytest.fixture
def isolated_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL migration tests")
    schema = "migration_test_" + uuid.uuid4().hex
    admin = create_engine(url, poolclass=NullPool)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped_url = scoped_url.render_as_string(hide_password=False)
    engine = create_engine(scoped_url, poolclass=NullPool)
    try:
        yield scoped_url, engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_concurrent_startup_and_repeat_preserve_data(isolated_database):
    url, engine = isolated_database
    env = {**os.environ, "DATABASE_URL": url}
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "app.migrate"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=45)
            assert process.returncode == 0, stdout + stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "5e62e48b1f36"
        connection.execute(text(
            "INSERT INTO users (user_id, email, password_hash, name) "
            "VALUES ('test', 'test@example.com', 'unused', 'test')"
        ))
    subprocess.run([sys.executable, "-m", "app.migrate"], env=env, check=True, timeout=45)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 1


def test_failed_migration_rolls_back_and_releases_lock(isolated_database, monkeypatch):
    url, engine = isolated_database
    monkeypatch.setattr(migrate.settings, "DATABASE_URL", url)
    original_upgrade = migrate.command.upgrade

    def fail_after_ddl(config, revision):
        config.attributes["connection"].execute(text("CREATE TABLE incomplete (id integer)"))
        raise RuntimeError("migration failed")

    monkeypatch.setattr(migrate.command, "upgrade", fail_after_ddl)
    with pytest.raises(RuntimeError, match="migration failed"):
        migrate.migrate()
    assert not inspect(engine).has_table("incomplete")
    monkeypatch.setattr(migrate.command, "upgrade", original_upgrade)
    migrate.migrate()
    assert inspect(engine).has_table("users")
