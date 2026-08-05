from __future__ import annotations

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

import psycopg
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

ConnectFactory = Callable[..., Any]

VECTOR_DATABASE_ENVS: dict[str, str] = {
    "nex-cx": "NEX_CX_VECTOR_DATABASE_URL",
}

SERVICE_DB_ENV_PREFIXES: dict[str, str] = {
    "nex-oa": "NEX_OA",
    "nex-ag": "NEX_AG",
    "nex-ae-api": "NEX_AE",
    "nex-cx": "NEX_CX",
    "nex-mo": "NEX_MO",
}

DATABASE_WORKLOADS = ("api", "worker")


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


@dataclass(frozen=True)
class DatabasePoolSettings:
    service_id: str
    env_prefix: str
    workload: str
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout_seconds: float = 30.0
    pool_recycle_seconds: int = 1800
    pool_pre_ping: bool = True
    statement_timeout_ms: int = 30000


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


def database_pool_settings(
    service_id: str,
    *,
    workload: str = "api",
    environ: Mapping[str, str] | None = None,
) -> DatabasePoolSettings:
    env = environ if environ is not None else os.environ
    env_prefix = service_database_env_prefix(service_id)
    normalized_workload = workload.lower()
    if normalized_workload not in DATABASE_WORKLOADS:
        raise DatabaseConfigError(f"unsupported database workload: {workload}")

    defaults = _default_pool_settings(
        service_id=service_id,
        env_prefix=env_prefix,
        workload=normalized_workload,
    )
    return DatabasePoolSettings(
        service_id=service_id,
        env_prefix=env_prefix,
        workload=normalized_workload,
        pool_size=_positive_int_env(
            env,
            _pool_env_names(env_prefix, "POOL_SIZE", normalized_workload),
            default=defaults.pool_size,
        ),
        max_overflow=_non_negative_int_env(
            env,
            _pool_env_names(env_prefix, "MAX_OVERFLOW", normalized_workload),
            default=defaults.max_overflow,
        ),
        pool_timeout_seconds=_positive_float_env(
            env,
            _pool_env_names(env_prefix, "POOL_TIMEOUT_SECONDS", normalized_workload),
            default=defaults.pool_timeout_seconds,
        ),
        pool_recycle_seconds=_positive_int_env(
            env,
            _pool_env_names(env_prefix, "POOL_RECYCLE_SECONDS", normalized_workload),
            default=defaults.pool_recycle_seconds,
        ),
        pool_pre_ping=_bool_env(
            env,
            _pool_env_names(env_prefix, "POOL_PRE_PING", normalized_workload),
            default=defaults.pool_pre_ping,
        ),
        statement_timeout_ms=_non_negative_int_env(
            env,
            _pool_env_names(env_prefix, "STATEMENT_TIMEOUT_MS", normalized_workload),
            default=defaults.statement_timeout_ms,
        ),
    )


def service_database_env_prefix(service_id: str) -> str:
    try:
        return SERVICE_DB_ENV_PREFIXES[service_id]
    except KeyError as exc:
        raise DatabaseConfigError(f"unknown service id: {service_id}") from exc


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
    pool_settings: DatabasePoolSettings | None = None,
) -> Engine:
    sqlalchemy_url = sqlalchemy_database_url(database_url)
    settings = pool_settings or DatabasePoolSettings(
        service_id="unknown",
        env_prefix="NEX",
        workload="api",
        pool_pre_ping=pool_pre_ping,
    )
    engine = create_engine(
        sqlalchemy_url,
        future=True,
        **_engine_pool_kwargs(sqlalchemy_url, settings),
    )
    _install_statement_timeout(engine, settings.statement_timeout_ms)
    return engine


def sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return f"postgresql+psycopg://{database_url.removeprefix('postgresql://')}"
    return database_url


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self.session = self._session_factory()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None

    @property
    def db(self) -> Session:
        if self.session is None:
            raise RuntimeError("unit of work session is not active")
        return self.session


def build_unit_of_work(session_factory: sessionmaker[Session]) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(session_factory)


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


def _default_pool_settings(
    *,
    service_id: str,
    env_prefix: str,
    workload: str,
) -> DatabasePoolSettings:
    if workload == "worker":
        return DatabasePoolSettings(
            service_id=service_id,
            env_prefix=env_prefix,
            workload=workload,
            pool_size=3,
            max_overflow=3,
            pool_timeout_seconds=30.0,
            pool_recycle_seconds=1800,
            pool_pre_ping=True,
            statement_timeout_ms=60000,
        )
    return DatabasePoolSettings(
        service_id=service_id,
        env_prefix=env_prefix,
        workload=workload,
    )


def _pool_env_names(
    env_prefix: str,
    suffix: str,
    workload: str,
) -> tuple[str, ...]:
    base_name = f"{env_prefix}_DB_{suffix}"
    if workload == "api":
        return (base_name,)
    return (f"{env_prefix}_DB_{workload.upper()}_{suffix}", base_name)


def _positive_int_env(
    env: Mapping[str, str],
    names: tuple[str, ...],
    *,
    default: int,
) -> int:
    raw_value = _first_env_value(env, names)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise DatabaseConfigError(f"{names[0]} must be an integer") from exc
    if value < 1:
        raise DatabaseConfigError(f"{names[0]} must be greater than 0")
    return value


def _non_negative_int_env(
    env: Mapping[str, str],
    names: tuple[str, ...],
    *,
    default: int,
) -> int:
    raw_value = _first_env_value(env, names)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise DatabaseConfigError(f"{names[0]} must be an integer") from exc
    if value < 0:
        raise DatabaseConfigError(f"{names[0]} must be greater than or equal to 0")
    return value


def _positive_float_env(
    env: Mapping[str, str],
    names: tuple[str, ...],
    *,
    default: float,
) -> float:
    raw_value = _first_env_value(env, names)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise DatabaseConfigError(f"{names[0]} must be a number") from exc
    if value <= 0:
        raise DatabaseConfigError(f"{names[0]} must be greater than 0")
    return value


def _bool_env(
    env: Mapping[str, str],
    names: tuple[str, ...],
    *,
    default: bool,
) -> bool:
    raw_value = _first_env_value(env, names)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise DatabaseConfigError(f"{names[0]} must be a boolean")


def _first_env_value(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value != "":
            return value
    return None


def _engine_pool_kwargs(
    database_url: str,
    settings: DatabasePoolSettings,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "pool_pre_ping": settings.pool_pre_ping,
        "pool_recycle": settings.pool_recycle_seconds,
    }
    try:
        backend = make_url(database_url).get_backend_name()
    except SQLAlchemyError:
        backend = ""
    if backend != "sqlite":
        kwargs.update(
            {
                "pool_size": settings.pool_size,
                "max_overflow": settings.max_overflow,
                "pool_timeout": settings.pool_timeout_seconds,
            }
        )
    return kwargs


def _install_statement_timeout(engine: Engine, statement_timeout_ms: int) -> None:
    if statement_timeout_ms <= 0:
        return
    if engine.url.get_backend_name() != "postgresql":
        return

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection: Any, connection_record: Any) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(statement_timeout_ms),),
            )
