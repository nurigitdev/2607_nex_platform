from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from nex_eos import (
    EOS_TEST_RESET_CONFIRMATION,
    build_eos_database_runtime,
    reset_eos_test_database,
)
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import make_url, text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S08_POSTGRES_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason=(
        "NEX_EOS_TEST_DATABASE_URL and NEX_EOS_P8_S08_POSTGRES_SMOKE=1 "
        "are required for protected EOS PostgreSQL smoke"
    ),
)


def _schema_database_url(database_url: str, schema_name: str) -> str:
    parsed = make_url(database_url)
    scoped = parsed.update_query_dict({"options": f"-csearch_path={schema_name}"})
    return scoped.render_as_string(hide_password=False)


def test_s08_actual_postgres_fresh_rerun_rollback_reset_and_zero_residue() -> None:
    schema_name = f"p8_s08_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )

    scoped_url = _schema_database_url(DATABASE_URL, schema_name)
    try:
        fresh = run_service_migrations(
            "nex-eos",
            database_url=scoped_url,
            profile="test",
        )
        rerun = run_service_migrations(
            "nex-eos",
            database_url=scoped_url,
            profile="test",
        )
        expected_versions = tuple(
            migration.version for migration in load_migrations("nex-eos")
        )
        assert fresh.applied == expected_versions
        assert fresh.skipped == ()
        assert rerun.applied == ()
        assert rerun.skipped == expected_versions

        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        try:
            with (
                pytest.raises(RuntimeError, match="rollback probe"),
                runtime.transaction() as transaction,
            ):
                transaction.db.execute(
                    text(
                        "INSERT INTO schema_migrations "
                        "(version, description) VALUES "
                        "('p8_s08_rollback_probe', 'must roll back')"
                    )
                )
                raise RuntimeError("rollback probe")
            with runtime.engine.connect() as connection:
                rolled_back = connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = 'p8_s08_rollback_probe'"
                    )
                ).scalar_one()
            assert rolled_back == 0
        finally:
            runtime.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )

    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    try:
        with runtime.engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS eos_s08_reset_probe "
                    "(id BIGSERIAL PRIMARY KEY, marker TEXT NOT NULL)"
                )
            )
            connection.execute(
                text("INSERT INTO eos_s08_reset_probe (marker) VALUES ('reset-me')")
            )

        result = reset_eos_test_database(
            database_url=DATABASE_URL,
            confirmation=EOS_TEST_RESET_CONFIRMATION,
        )
        assert "eos_s08_reset_probe" in result.truncated_tables

        with runtime.engine.connect() as connection:
            remaining = connection.execute(
                text("SELECT count(*) FROM eos_s08_reset_probe")
            ).scalar_one()
            baseline = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2500_eos_schema_migrations_baseline'"
                )
            ).scalar_one()
        assert remaining == 0
        assert baseline == 1
    finally:
        with runtime.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS eos_s08_reset_probe"))
        runtime.dispose()
