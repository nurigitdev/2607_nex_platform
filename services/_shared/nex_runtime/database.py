from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

ConnectFactory = Callable[..., Any]

VECTOR_DATABASE_ENVS: dict[str, str] = {
    "nex-cx": "NEX_CX_VECTOR_DATABASE_URL",
}


@dataclass(frozen=True)
class DatabaseSettings:
    service_id: str
    database_env: str
    database_url: str
    redacted_database_url: str
    vector_database_env: str | None = None
    vector_database_url: str | None = None
    redacted_vector_database_url: str | None = None
    vector_uses_primary: bool = True


class DatabaseConfigError(ValueError):
    pass


def service_database_settings(
    *,
    service_id: str,
    database_env: str,
    environ: Mapping[str, str] | None = None,
) -> DatabaseSettings:
    env = environ if environ is not None else os.environ
    database_url = required_database_url(database_env, env)
    vector_database_env = VECTOR_DATABASE_ENVS.get(service_id)
    vector_database_url = None
    redacted_vector_database_url = None
    vector_uses_primary = True
    if vector_database_env is not None:
        vector_database_url = env.get(vector_database_env) or database_url
        if is_placeholder_database_url(vector_database_url):
            raise DatabaseConfigError(
                f"database URL env {vector_database_env} still contains placeholder password"
            )
        redacted_vector_database_url = redact_database_url(vector_database_url)
        vector_uses_primary = vector_database_url == database_url
    return DatabaseSettings(
        service_id=service_id,
        database_env=database_env,
        database_url=database_url,
        redacted_database_url=redact_database_url(database_url),
        vector_database_env=vector_database_env,
        vector_database_url=vector_database_url,
        redacted_vector_database_url=redacted_vector_database_url,
        vector_uses_primary=vector_uses_primary,
    )


def required_database_url(
    database_env: str,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    database_url = env.get(database_env)
    if not database_url:
        raise DatabaseConfigError(f"missing database URL env {database_env}")
    if is_placeholder_database_url(database_url):
        raise DatabaseConfigError(
            f"database URL env {database_env} still contains placeholder password"
        )
    return database_url


def is_placeholder_database_url(database_url: str) -> bool:
    lowered = database_url.lower()
    return "<password>" in lowered or "password>" in lowered


def redact_database_url(database_url: str) -> str:
    try:
        url = make_url(database_url)
    except SQLAlchemyError:
        return "<redacted-database-url>"
    if url.password is None:
        return url.render_as_string(hide_password=False)
    return url.render_as_string(hide_password=True)


def build_engine(
    database_url: str,
    *,
    pool_pre_ping: bool = True,
) -> Engine:
    return create_engine(database_url, future=True, pool_pre_ping=pool_pre_ping)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def check_database_readiness(
    database_env: str,
    *,
    environ: Mapping[str, str] | None = None,
    connect: ConnectFactory | None = None,
    connect_timeout: int = 2,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    connect_factory = connect if connect is not None else psycopg.connect
    started = time.perf_counter()
    database_url = env.get(database_env)
    if not database_url:
        return _readiness_problem(
            database_env=database_env,
            error_code="DATABASE_URL_MISSING",
            started=started,
            latency_ms=0,
        )
    if is_placeholder_database_url(database_url):
        return _readiness_problem(
            database_env=database_env,
            error_code="DATABASE_URL_PLACEHOLDER",
            started=started,
            latency_ms=0,
        )

    try:
        with connect_factory(database_url, connect_timeout=connect_timeout) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select current_database(), current_user")
                database_name, user_name = cursor.fetchone()
    except Exception:
        return _readiness_problem(
            database_env=database_env,
            error_code="DATABASE_CONNECTION_FAILED",
            started=started,
        )

    return {
        "name": "database",
        "ok": True,
        "database_env": database_env,
        "database_name": database_name,
        "database_user": user_name,
        "latency_ms": _elapsed_ms(started),
    }


def check_sqlalchemy_engine(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("select 1")).scalar_one() == 1


def _readiness_problem(
    *,
    database_env: str,
    error_code: str,
    started: float,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "name": "database",
        "ok": False,
        "database_env": database_env,
        "error_code": error_code,
        "latency_ms": _elapsed_ms(started) if latency_ms is None else latency_ms,
    }


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
