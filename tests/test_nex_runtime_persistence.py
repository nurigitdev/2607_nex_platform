from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    PERSISTENCE_MODE_MEMORY,
    PERSISTENCE_MODE_POSTGRES,
    PersistenceConfigError,
    SERVICE_SPECS,
    ServicePersistenceRuntime,
    SqlAlchemyJobQueue,
    SqlAlchemyOperationalEventStore,
    attach_service_persistence_runtime,
    build_service_app,
    build_service_persistence_runtime,
    normalize_persistence_mode,
    persistence_mode_env_names,
)


def test_normalize_persistence_mode_accepts_memory_and_postgres_aliases() -> None:
    assert normalize_persistence_mode(None) == PERSISTENCE_MODE_MEMORY
    assert normalize_persistence_mode("local_mock") == PERSISTENCE_MODE_MEMORY
    assert normalize_persistence_mode("in_memory") == PERSISTENCE_MODE_MEMORY
    assert normalize_persistence_mode("postgresql") == PERSISTENCE_MODE_POSTGRES
    assert normalize_persistence_mode("sqlalchemy") == PERSISTENCE_MODE_POSTGRES


def test_normalize_persistence_mode_rejects_unknown_value() -> None:
    with pytest.raises(PersistenceConfigError, match="unsupported persistence mode"):
        normalize_persistence_mode("sqlite")


def test_persistence_mode_env_names_are_service_specific_then_global() -> None:
    assert persistence_mode_env_names("nex-cx") == (
        "NEX_CX_PERSISTENCE_MODE",
        "NEX_PERSISTENCE_MODE",
    )

    with pytest.raises(PersistenceConfigError, match="unknown service id"):
        persistence_mode_env_names("nex-unknown")


def test_memory_runtime_is_default_and_does_not_require_database_url() -> None:
    runtime = build_service_persistence_runtime(
        service_id="nex-cx",
        database_env="NEX_CX_DATABASE_URL",
        environ={},
    )

    assert isinstance(runtime, ServicePersistenceRuntime)
    assert runtime.mode == PERSISTENCE_MODE_MEMORY
    assert runtime.database_env is None
    assert runtime.redacted_database_url is None
    assert isinstance(runtime.job_queue, InMemoryJobQueue)
    assert isinstance(runtime.operational_event_store, InMemoryOperationalEventStore)
    assert runtime.to_summary() == {
        "service_id": "nex-cx",
        "mode": "memory",
        "database_env": None,
        "redacted_database_url": None,
        "job_queue": "InMemoryJobQueue",
        "operational_event_store": "InMemoryOperationalEventStore",
    }


def test_service_specific_persistence_mode_overrides_global_mode() -> None:
    runtime = build_service_persistence_runtime(
        service_id="nex-cx",
        database_env="NEX_CX_DATABASE_URL",
        environ={
            "NEX_PERSISTENCE_MODE": "postgres",
            "NEX_CX_PERSISTENCE_MODE": "memory",
        },
    )

    assert runtime.mode == PERSISTENCE_MODE_MEMORY


def test_postgres_runtime_builds_sqlalchemy_stores_with_api_and_worker_pools() -> None:
    engine_calls: list[dict[str, Any]] = []
    session_calls: list[object] = []

    def fake_engine_factory(database_url: str, *, pool_settings: object) -> object:
        engine = SimpleNamespace(database_url=database_url, pool_settings=pool_settings)
        engine_calls.append(
            {
                "database_url": database_url,
                "workload": pool_settings.workload,
                "pool_size": pool_settings.pool_size,
            }
        )
        return engine

    def fake_session_factory_builder(engine: object) -> object:
        session_calls.append(engine)
        return f"session:{engine.pool_settings.workload}"

    runtime = build_service_persistence_runtime(
        service_id="nex-cx",
        database_env="NEX_CX_DATABASE_URL",
        environ={
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:secret@localhost/nex_cx_dev",
            "NEX_CX_DB_POOL_SIZE": "7",
            "NEX_CX_DB_WORKER_POOL_SIZE": "2",
        },
        engine_factory=fake_engine_factory,
        session_factory_builder=fake_session_factory_builder,
    )

    assert runtime.mode == PERSISTENCE_MODE_POSTGRES
    assert runtime.database_env == "NEX_CX_DATABASE_URL"
    assert runtime.redacted_database_url == "postgresql://nex_cx_user:***@localhost/nex_cx_dev"
    assert isinstance(runtime.job_queue, SqlAlchemyJobQueue)
    assert isinstance(runtime.operational_event_store, SqlAlchemyOperationalEventStore)
    assert [call["workload"] for call in engine_calls] == ["api", "worker"]
    assert [call["pool_size"] for call in engine_calls] == [7, 2]
    assert len(session_calls) == 2
    assert "secret" not in str(runtime.to_summary())


@pytest.mark.parametrize(
    "environ",
    [
        {"NEX_CX_PERSISTENCE_MODE": "postgres"},
        {
            "NEX_CX_PERSISTENCE_MODE": "postgres",
            "NEX_CX_DATABASE_URL": "postgresql://nex_cx_user:<password>@localhost/nex_cx_dev",
        },
    ],
)
def test_postgres_runtime_rejects_missing_or_placeholder_database_url(
    environ: dict[str, str],
) -> None:
    with pytest.raises(PersistenceConfigError):
        build_service_persistence_runtime(
            service_id="nex-cx",
            database_env="NEX_CX_DATABASE_URL",
            environ=environ,
        )


def test_attach_service_persistence_runtime_sets_app_state() -> None:
    spec = SERVICE_SPECS["nex-ag"]
    app = build_service_app(spec)

    runtime = attach_service_persistence_runtime(app, spec, environ={})

    assert app.state.nex_persistence is runtime
    assert runtime.to_summary()["service_id"] == "nex-ag"
