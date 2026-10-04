from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .database import (
    DatabasePoolSettings,
    build_engine,
    build_session_factory,
    check_sqlalchemy_engine,
    database_pool_settings,
)
from .postgres_orchestration import (
    POSTGRES_SERVICE_ORDER,
    PlatformPostgresRestartEvidence,
    build_platform_postgres_restart_evidence,
    build_postgres_phase_evidence,
)
from .postgres_targets import (
    PostgresTargetConfigError,
    resolve_postgres_test_targets,
)


EngineFactory = Callable[..., Engine]
SessionFactoryBuilder = Callable[[Engine], sessionmaker[Session]]
EngineChecker = Callable[[Engine], bool]
SessionChecker = Callable[[sessionmaker[Session]], bool]


class PostgresPoolLifecycleError(RuntimeError):
    def __init__(
        self,
        failure_code: str,
        service_id: str | None = None,
        workload: str | None = None,
    ) -> None:
        self.failure_code = failure_code
        self.service_id = service_id
        self.workload = workload
        super().__init__(failure_code)


@dataclass(frozen=True)
class PostgresPoolHandle:
    service_id: str
    workload: str
    settings: DatabasePoolSettings
    engine: Engine = field(repr=False)
    session_factory: sessionmaker[Session] = field(repr=False)


class PlatformPostgresPoolLifecycle:
    def __init__(
        self,
        handles: tuple[PostgresPoolHandle, ...],
        evidence: PlatformPostgresRestartEvidence,
    ) -> None:
        self._handles = handles
        self._evidence = evidence
        self._pending_disposal = {
            id(handle.engine): handle.engine for handle in handles
        }
        self._state = "READY"

    @classmethod
    def build(
        cls,
        environ: Mapping[str, str],
        *,
        engine_factory: EngineFactory = build_engine,
        session_factory_builder: SessionFactoryBuilder = build_session_factory,
        engine_checker: EngineChecker = check_sqlalchemy_engine,
        session_checker: SessionChecker | None = None,
    ) -> PlatformPostgresPoolLifecycle:
        try:
            targets = resolve_postgres_test_targets(
                environ, service_ids=POSTGRES_SERVICE_ORDER
            )
        except PostgresTargetConfigError as exc:
            raise PostgresPoolLifecycleError("configuration_invalid") from exc

        check_session = session_checker or _check_session_factory
        handles: list[PostgresPoolHandle] = []
        created_engines: list[Engine] = []
        evidence = []
        for target in targets:
            service_id = target.target.service_id
            for workload in ("api", "worker"):
                try:
                    settings = database_pool_settings(
                        service_id, workload=workload, environ=environ
                    )
                    engine = engine_factory(
                        target.database_url,
                        pool_settings=settings,
                    )
                    if any(engine is item for item in created_engines):
                        raise ValueError("pool_engine_reused")
                    created_engines.append(engine)
                    session_factory = session_factory_builder(engine)
                    if not engine_checker(engine):
                        raise ValueError("pool_engine_not_ready")
                    if not check_session(session_factory):
                        raise ValueError("pool_session_not_ready")
                    handle = PostgresPoolHandle(
                        service_id,
                        workload,
                        settings,
                        engine,
                        session_factory,
                    )
                    handles.append(handle)
                except Exception as exc:
                    _dispose_engines(tuple(created_engines))
                    raise PostgresPoolLifecycleError(
                        "pool_initialization_failed", service_id, workload
                    ) from exc
            evidence.append(
                build_postgres_phase_evidence(
                    service_id=service_id,
                    phase="POOL_READINESS",
                    status="PASSED",
                    evidence_codes=(
                        "api_pool_ready",
                        "worker_pool_ready",
                        "session_factories_ready",
                    ),
                )
            )
        return cls(
            tuple(handles),
            build_platform_postgres_restart_evidence(
                run_id="s133-pool-lifecycle",
                state="PASSED",
                records=evidence,
            ),
        )

    @property
    def handles(self) -> tuple[PostgresPoolHandle, ...]:
        return self._handles

    def engine_identity_tokens(self) -> frozenset[int]:
        return frozenset(id(handle.engine) for handle in self._handles)

    def public_status(self) -> dict[str, Any]:
        return {
            "schema_version": "platform_postgres_pool_lifecycle.v1",
            "profile": "test",
            "state": self._state,
            "service_count": len({item.service_id for item in self._handles}),
            "pool_count": len(self._handles),
            "pending_disposal_count": len(self._pending_disposal),
            "pools": [
                {
                    "service_id": item.service_id,
                    "workload": item.workload,
                    "pool_size": item.settings.pool_size,
                    "max_overflow": item.settings.max_overflow,
                    "pool_timeout_seconds": item.settings.pool_timeout_seconds,
                    "pool_recycle_seconds": item.settings.pool_recycle_seconds,
                    "pool_pre_ping": item.settings.pool_pre_ping,
                    "statement_timeout_ms": item.settings.statement_timeout_ms,
                }
                for item in self._handles
            ],
            "evidence": self._evidence.to_public_projection(),
        }

    def dispose(self) -> dict[str, Any]:
        if not self._pending_disposal:
            self._state = "DISPOSED"
            return self.public_status()
        failures = []
        for identity, engine in tuple(reversed(tuple(self._pending_disposal.items()))):
            try:
                engine.dispose()
            except Exception:
                failures.append(identity)
            else:
                self._pending_disposal.pop(identity, None)
        if failures:
            self._state = "DISPOSE_FAILED"
            raise PostgresPoolLifecycleError("pool_disposal_failed")
        self._state = "DISPOSED"
        return self.public_status()


def _check_session_factory(factory: sessionmaker[Session]) -> bool:
    with factory() as session:
        return session.execute(text("select 1")).scalar_one() == 1


def _dispose_engines(engines: tuple[Engine, ...]) -> None:
    seen: set[int] = set()
    for engine in reversed(engines):
        if id(engine) in seen:
            continue
        seen.add(id(engine))
        try:
            engine.dispose()
        except Exception:
            continue
