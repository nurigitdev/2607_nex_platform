from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from nex_runtime import (
    DatabaseConfigError,
    DatabasePoolSettings,
    DatabaseSettings,
    SqlAlchemyUnitOfWork,
    build_engine,
    build_session_factory,
    build_unit_of_work,
    database_pool_settings,
    service_database_settings,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .config import DATABASE_ENV, SERVICE_ID

EngineFactory = Callable[..., Engine]
SessionFactoryBuilder = Callable[[Engine], sessionmaker[Session]]


class EosDatabaseRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class EosDatabaseRuntime:
    settings: DatabaseSettings
    pool_settings: DatabasePoolSettings
    engine: Engine
    session_factory: sessionmaker[Session]

    def transaction(self) -> SqlAlchemyUnitOfWork:
        return build_unit_of_work(self.session_factory)

    def public_projection(self) -> dict[str, Any]:
        return {
            "service_id": self.settings.service_id,
            "database_env": self.settings.database_env,
            "redacted_database_url": self.settings.redacted_database_url,
            "pool": asdict(self.pool_settings),
        }

    def dispose(self) -> None:
        self.engine.dispose()


def build_eos_database_runtime(
    *,
    environ: Mapping[str, str],
    database_env: str = DATABASE_ENV,
    workload: str = "api",
    engine_factory: EngineFactory = build_engine,
    session_factory_builder: SessionFactoryBuilder = build_session_factory,
) -> EosDatabaseRuntime:
    try:
        settings = service_database_settings(
            service_id=SERVICE_ID,
            database_env=database_env,
            environ=environ,
        )
        pool_settings = database_pool_settings(
            SERVICE_ID,
            workload=workload,
            environ=environ,
        )
        engine = engine_factory(
            settings.database_url,
            pool_settings=pool_settings,
        )
        session_factory = session_factory_builder(engine)
    except (DatabaseConfigError, SQLAlchemyError) as exc:
        raise EosDatabaseRuntimeError(
            "NeX-EOS database runtime configuration is invalid"
        ) from exc
    return EosDatabaseRuntime(
        settings=settings,
        pool_settings=pool_settings,
        engine=engine,
        session_factory=session_factory,
    )
