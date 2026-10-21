from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from nex_runtime import psycopg_database_url
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

EOS_TEST_DATABASE_NAME = "nex_eos_test"
EOS_DATABASE_ROLE_NAME = "nex_eos_user"
EOS_TEST_RESET_CONFIRMATION = "RESET_NEX_EOS_TEST"
_EOS_TABLE_NAME = re.compile(r"^eos_[a-z0-9_]+$")

ConnectFactory = Callable[..., Any]


class EosTestDatabaseResetError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass(frozen=True)
class EosTestDatabaseResetResult:
    database_name: str
    database_role: str
    truncated_tables: tuple[str, ...]

    def to_public_projection(self) -> dict[str, Any]:
        return {
            "database_name": self.database_name,
            "database_role": self.database_role,
            "truncated_tables": list(self.truncated_tables),
            "schema_migrations_preserved": True,
        }


def reset_eos_test_database(
    *,
    database_url: str,
    confirmation: str,
    connect: ConnectFactory = psycopg.connect,
) -> EosTestDatabaseResetResult:
    if confirmation != EOS_TEST_RESET_CONFIRMATION:
        raise EosTestDatabaseResetError("eos.test_reset_confirmation_invalid")
    _validate_reset_target_url(database_url)

    table_names: tuple[str, ...] = ()
    try:
        with connect(
            psycopg_database_url(database_url),
            autocommit=False,
        ) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database(), current_user")
                    identity = cursor.fetchone()
                    if identity != (
                        EOS_TEST_DATABASE_NAME,
                        EOS_DATABASE_ROLE_NAME,
                    ):
                        raise EosTestDatabaseResetError(
                            "eos.test_reset_identity_mismatch"
                        )
                    cursor.execute(
                        "SELECT tablename FROM pg_catalog.pg_tables "
                        "WHERE schemaname = 'public' ORDER BY tablename"
                    )
                    table_names = tuple(
                        row[0]
                        for row in cursor.fetchall()
                        if isinstance(row[0], str)
                        and _EOS_TABLE_NAME.fullmatch(row[0]) is not None
                    )
                    if table_names:
                        cursor.execute(
                            sql.SQL(
                                "TRUNCATE TABLE {} RESTART IDENTITY CASCADE"
                            ).format(
                                sql.SQL(", ").join(
                                    sql.Identifier(name) for name in table_names
                                )
                            )
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
    except EosTestDatabaseResetError:
        raise
    except Exception as exc:
        raise EosTestDatabaseResetError("eos.test_reset_failed") from exc

    return EosTestDatabaseResetResult(
        database_name=EOS_TEST_DATABASE_NAME,
        database_role=EOS_DATABASE_ROLE_NAME,
        truncated_tables=table_names,
    )


def _validate_reset_target_url(database_url: str) -> None:
    try:
        parsed = make_url(database_url)
    except SQLAlchemyError as exc:
        raise EosTestDatabaseResetError("eos.test_reset_target_invalid") from exc
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EOS_TEST_DATABASE_NAME
        or parsed.username != EOS_DATABASE_ROLE_NAME
    ):
        raise EosTestDatabaseResetError("eos.test_reset_target_invalid")
