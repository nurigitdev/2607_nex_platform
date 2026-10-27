from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from nex_runtime import (
    DatabaseConfigError,
    DatabasePoolSettings,
    DatabaseSettings,
    SqlAlchemyJobQueue,
    SqlAlchemyUnitOfWork,
    SqlAlchemyWorkerHeartbeatStore,
    build_engine,
    build_session_factory,
    build_unit_of_work,
    database_pool_settings,
    service_database_settings,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .admission import WaEvidenceAdmissionService
from .config import DATABASE_ENV, SERVICE_ID
from .work_assets import SqlAlchemyWorkAssetRepository
from .work_evidence import SqlAlchemyWorkEvidenceRepository

WA_COMMON_RUNTIME_MIGRATIONS = (
    "2600_wa_schema_migrations_baseline",
    "2601_wa_service_job_queue",
    "2602_wa_worker_heartbeat",
)
WA_REQUIRED_MIGRATIONS = (
    *WA_COMMON_RUNTIME_MIGRATIONS,
    "2603_wa_work_evidence",
    "2604_wa_work_asset",
    "2605_wa_work_asset_evidence",
)

EngineFactory = Callable[..., Engine]
SessionFactoryBuilder = Callable[[Engine], sessionmaker[Session]]


class WaPersistenceError(ValueError):
    pass


@dataclass(frozen=True)
class WaPersistenceRuntime:
    settings: DatabaseSettings
    api_pool_settings: DatabasePoolSettings
    worker_pool_settings: DatabasePoolSettings
    api_engine: Engine
    worker_engine: Engine
    api_session_factory: sessionmaker[Session]
    worker_session_factory: sessionmaker[Session]
    job_queue: SqlAlchemyJobQueue
    worker_heartbeat_store: SqlAlchemyWorkerHeartbeatStore
    work_evidence_repository: SqlAlchemyWorkEvidenceRepository
    work_asset_repository: SqlAlchemyWorkAssetRepository
    evidence_admission_service: WaEvidenceAdmissionService

    def transaction(self) -> SqlAlchemyUnitOfWork:
        return build_unit_of_work(self.api_session_factory)

    def migration_readiness(self) -> dict[str, Any]:
        try:
            with self.api_session_factory() as session:
                rows = session.execute(
                    text("SELECT version FROM schema_migrations")
                ).all()
            applied = {str(row[0]) for row in rows}
        except SQLAlchemyError:
            return {
                "name": "wa_migrations",
                "ok": False,
                "error_code": "WA_MIGRATION_READINESS_FAILED",
            }
        missing = tuple(
            version for version in WA_REQUIRED_MIGRATIONS if version not in applied
        )
        return {
            "name": "wa_migrations",
            "ok": not missing,
            "required_count": len(WA_REQUIRED_MIGRATIONS),
            "missing_versions": list(missing),
        }

    def public_projection(self) -> dict[str, Any]:
        return {
            "service_id": self.settings.service_id,
            "database_env": self.settings.database_env,
            "redacted_database_url": self.settings.redacted_database_url,
            "api_pool": asdict(self.api_pool_settings),
            "worker_pool": asdict(self.worker_pool_settings),
            "job_queue": self.job_queue.__class__.__name__,
            "worker_heartbeat_store": self.worker_heartbeat_store.__class__.__name__,
            "work_evidence_repository": self.work_evidence_repository.__class__.__name__,
            "work_asset_repository": self.work_asset_repository.__class__.__name__,
            "evidence_admission_service": self.evidence_admission_service.__class__.__name__,
        }

    def dispose(self) -> None:
        self.worker_engine.dispose()
        if self.api_engine is not self.worker_engine:
            self.api_engine.dispose()


def build_wa_persistence_runtime(
    *,
    environ: Mapping[str, str],
    database_env: str = DATABASE_ENV,
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> WaPersistenceRuntime:
    api_engine: Engine | None = None
    worker_engine: Engine | None = None
    try:
        settings = service_database_settings(
            service_id=SERVICE_ID,
            database_env=database_env,
            environ=environ,
        )
        api_pool = database_pool_settings(
            SERVICE_ID, workload="api", environ=environ
        )
        worker_pool = database_pool_settings(
            SERVICE_ID, workload="worker", environ=environ
        )
        api_engine = engine_factory(
            settings.database_url,
            pool_settings=api_pool,
        )
        worker_engine = engine_factory(
            settings.database_url,
            pool_settings=worker_pool,
        )
        api_sessions = session_factory_builder(api_engine)
        worker_sessions = session_factory_builder(worker_engine)
    except (DatabaseConfigError, SQLAlchemyError) as exc:
        if worker_engine is not None:
            worker_engine.dispose()
        if api_engine is not None and api_engine is not worker_engine:
            api_engine.dispose()
        raise WaPersistenceError(
            "NeX-WA persistence configuration is invalid"
        ) from exc

    work_evidence_repository = SqlAlchemyWorkEvidenceRepository(api_sessions)
    work_asset_repository = SqlAlchemyWorkAssetRepository(api_sessions)
    return WaPersistenceRuntime(
        settings=settings,
        api_pool_settings=api_pool,
        worker_pool_settings=worker_pool,
        api_engine=api_engine,
        worker_engine=worker_engine,
        api_session_factory=api_sessions,
        worker_session_factory=worker_sessions,
        job_queue=SqlAlchemyJobQueue(worker_sessions),
        worker_heartbeat_store=SqlAlchemyWorkerHeartbeatStore(worker_sessions),
        work_evidence_repository=work_evidence_repository,
        work_asset_repository=work_asset_repository,
        evidence_admission_service=WaEvidenceAdmissionService(
            api_sessions,
            evidence_repository=work_evidence_repository,
            asset_repository=work_asset_repository,
        ),
    )
