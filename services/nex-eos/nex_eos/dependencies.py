from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nex_runtime import build_service_token_admission_runtime
from nex_runtime.service_token_admission import ServiceTokenAdmissionRuntime

from .business_transactions import (
    EosBusinessTransactionCoordinator,
    SqlAlchemyEosBusinessTransactionCoordinator,
)
from .config import EosSettings
from .health import build_configuration_readiness_check
from .organization import SqlAlchemyEosOrganizationRepository
from .persistence import EosDatabaseRuntime, build_eos_database_runtime
from .projects import SqlAlchemyEosProjectRepository


@dataclass(frozen=True)
class EosDependencies:
    service_token_admission: ServiceTokenAdmissionRuntime
    readiness_checks: tuple[Callable[[], Mapping[str, Any]], ...]
    database_runtime: EosDatabaseRuntime | None
    business_transactions: EosBusinessTransactionCoordinator | None
    organization: SqlAlchemyEosOrganizationRepository | None
    projects: SqlAlchemyEosProjectRepository | None


def build_eos_dependencies(
    settings: EosSettings,
    *,
    environ: Mapping[str, str],
) -> EosDependencies:
    database_runtime = (
        build_eos_database_runtime(environ=environ)
        if environ.get(settings.database_env)
        else None
    )
    business_transactions = (
        SqlAlchemyEosBusinessTransactionCoordinator(
            database_runtime.session_factory,
        )
        if database_runtime is not None
        else None
    )
    organization = (
        SqlAlchemyEosOrganizationRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    projects = (
        SqlAlchemyEosProjectRepository(database_runtime.session_factory)
        if database_runtime is not None
        else None
    )
    return EosDependencies(
        service_token_admission=build_service_token_admission_runtime(
            expected_audience=settings.service_id,
            environ=environ,
        ),
        readiness_checks=(build_configuration_readiness_check(settings),),
        database_runtime=database_runtime,
        business_transactions=business_transactions,
        organization=organization,
        projects=projects,
    )
