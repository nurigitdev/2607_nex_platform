from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .database import (
    DatabaseConfigError,
    build_engine,
    build_session_factory,
    database_pool_settings,
    redact_database_url,
    required_database_url,
    service_database_env_prefix,
)
from .jobs import InMemoryJobQueue, JobQueue, SqlAlchemyJobQueue
from .operational_events import (
    InMemoryOperationalEventStore,
    OperationalEventStore,
    SqlAlchemyOperationalEventStore,
)

PERSISTENCE_MODE_MEMORY = "memory"
PERSISTENCE_MODE_POSTGRES = "postgres"
PERSISTENCE_MODES = (PERSISTENCE_MODE_MEMORY, PERSISTENCE_MODE_POSTGRES)

_PERSISTENCE_MODE_ALIASES = {
    "": PERSISTENCE_MODE_MEMORY,
    "inmemory": PERSISTENCE_MODE_MEMORY,
    "in-memory": PERSISTENCE_MODE_MEMORY,
    "in_memory": PERSISTENCE_MODE_MEMORY,
    "local_mock": PERSISTENCE_MODE_MEMORY,
    "mock": PERSISTENCE_MODE_MEMORY,
    "memory": PERSISTENCE_MODE_MEMORY,
    "db": PERSISTENCE_MODE_POSTGRES,
    "persistent": PERSISTENCE_MODE_POSTGRES,
    "postgres": PERSISTENCE_MODE_POSTGRES,
    "postgresql": PERSISTENCE_MODE_POSTGRES,
    "sqlalchemy": PERSISTENCE_MODE_POSTGRES,
}

EngineFactory = Callable[..., Engine]
SessionFactoryBuilder = Callable[[Engine], sessionmaker[Session]]


class PersistenceConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServicePersistenceRuntime:
    service_id: str
    mode: str
    database_env: str | None
    redacted_database_url: str | None
    job_queue: JobQueue
    operational_event_store: OperationalEventStore
    api_engine: Engine | None = field(default=None, repr=False)
    worker_engine: Engine | None = field(default=None, repr=False)
    api_session_factory: sessionmaker[Session] | None = field(default=None, repr=False)
    worker_session_factory: sessionmaker[Session] | None = field(default=None, repr=False)

    def to_summary(self) -> dict[str, object]:
        return {
            "service_id": self.service_id,
            "mode": self.mode,
            "database_env": self.database_env,
            "redacted_database_url": self.redacted_database_url,
            "job_queue": self.job_queue.__class__.__name__,
            "operational_event_store": self.operational_event_store.__class__.__name__,
        }


def build_service_persistence_runtime(
    *,
    service_id: str,
    database_env: str,
    environ: Mapping[str, str] | None = None,
    mode: str | None = None,
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> ServicePersistenceRuntime:
    env = environ if environ is not None else os.environ
    resolved_mode = normalize_persistence_mode(
        mode or _first_env_value(env, persistence_mode_env_names(service_id))
    )
    if resolved_mode == PERSISTENCE_MODE_MEMORY:
        return ServicePersistenceRuntime(
            service_id=service_id,
            mode=resolved_mode,
            database_env=None,
            redacted_database_url=None,
            job_queue=InMemoryJobQueue(),
            operational_event_store=InMemoryOperationalEventStore(),
        )

    try:
        database_url = required_database_url(database_env, env)
        api_engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(service_id, workload="api", environ=env),
        )
        worker_engine = engine_factory(
            database_url,
            pool_settings=database_pool_settings(service_id, workload="worker", environ=env),
        )
    except DatabaseConfigError as exc:
        raise PersistenceConfigError(str(exc)) from exc

    api_session_factory = session_factory_builder(api_engine)
    worker_session_factory = session_factory_builder(worker_engine)
    return ServicePersistenceRuntime(
        service_id=service_id,
        mode=resolved_mode,
        database_env=database_env,
        redacted_database_url=redact_database_url(database_url),
        job_queue=SqlAlchemyJobQueue(worker_session_factory),
        operational_event_store=SqlAlchemyOperationalEventStore(api_session_factory),
        api_engine=api_engine,
        worker_engine=worker_engine,
        api_session_factory=api_session_factory,
        worker_session_factory=worker_session_factory,
    )


def attach_service_persistence_runtime(
    app: Any,
    spec: Any,
    *,
    environ: Mapping[str, str] | None = None,
    mode: str | None = None,
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> ServicePersistenceRuntime:
    runtime = build_service_persistence_runtime(
        service_id=spec.service_id,
        database_env=spec.database_env,
        environ=environ,
        mode=mode,
        engine_factory=engine_factory,
        session_factory_builder=session_factory_builder,
    )
    app.state.nex_persistence = runtime
    return runtime


def persistence_mode_env_names(service_id: str) -> tuple[str, str]:
    try:
        service_prefix = service_database_env_prefix(service_id)
    except DatabaseConfigError as exc:
        raise PersistenceConfigError(str(exc)) from exc
    return (f"{service_prefix}_PERSISTENCE_MODE", "NEX_PERSISTENCE_MODE")


def normalize_persistence_mode(value: str | None) -> str:
    raw_value = "" if value is None else value.strip().lower()
    try:
        return _PERSISTENCE_MODE_ALIASES[raw_value]
    except KeyError as exc:
        raise PersistenceConfigError(
            f"unsupported persistence mode: {value}; expected one of {', '.join(PERSISTENCE_MODES)}"
        ) from exc


def _first_env_value(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip() != "":
            return value
    return None
