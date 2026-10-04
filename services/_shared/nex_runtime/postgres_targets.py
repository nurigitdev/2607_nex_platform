from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .database import is_placeholder_database_url, required_database_url


CX_VECTOR_TEST_DATABASE_ENV = "NEX_CX_VECTOR_TEST_DATABASE_URL"
CX_VECTOR_RUNTIME_DATABASE_ENV = "NEX_CX_VECTOR_DATABASE_URL"


class PostgresTargetConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PostgresTestTarget:
    service_id: str
    test_database_env: str
    runtime_database_env: str
    expected_database_name: str
    expected_role_name: str


@dataclass(frozen=True)
class ResolvedPostgresTestTarget:
    target: PostgresTestTarget
    database_url: str = field(repr=False)
    drivername: str


POSTGRES_TEST_TARGETS = (
    PostgresTestTarget(
        "nex-oa",
        "NEX_OA_TEST_DATABASE_URL",
        "NEX_OA_DATABASE_URL",
        "nex_oa_test",
        "nex_oa_user",
    ),
    PostgresTestTarget(
        "nex-mo",
        "NEX_MO_TEST_DATABASE_URL",
        "NEX_MO_DATABASE_URL",
        "nex_mo_test",
        "nex_mo_user",
    ),
    PostgresTestTarget(
        "nex-cx",
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_CX_DATABASE_URL",
        "nex_cx_test",
        "nex_cx_user",
    ),
    PostgresTestTarget(
        "nex-ae-api",
        "NEX_AE_TEST_DATABASE_URL",
        "NEX_AE_DATABASE_URL",
        "nex_ae_test",
        "nex_ae_user",
    ),
    PostgresTestTarget(
        "nex-ag",
        "NEX_AG_TEST_DATABASE_URL",
        "NEX_AG_DATABASE_URL",
        "nex_ag_test",
        "nex_ag_user",
    ),
)


def resolve_postgres_test_targets(
    environ: Mapping[str, str],
    *,
    service_ids: Iterable[str] | None = None,
) -> tuple[ResolvedPostgresTestTarget, ...]:
    selected_ids = tuple(
        service_ids or (item.service_id for item in POSTGRES_TEST_TARGETS)
    )
    if len(set(selected_ids)) != len(selected_ids):
        raise PostgresTargetConfigError("service_ids_duplicate")
    by_service = {item.service_id: item for item in POSTGRES_TEST_TARGETS}
    unknown = tuple(
        service_id for service_id in selected_ids if service_id not in by_service
    )
    if unknown:
        raise PostgresTargetConfigError("service_id_unknown")

    resolved = tuple(
        _resolve_target(by_service[service_id], environ) for service_id in selected_ids
    )
    urls = [item.database_url for item in resolved]
    if len(set(urls)) != len(urls):
        raise PostgresTargetConfigError("database_url_must_be_service_local")
    return resolved


def build_postgres_test_runtime_overlay(
    environ: Mapping[str, str],
    *,
    service_ids: Iterable[str] | None = None,
) -> dict[str, str]:
    resolved = resolve_postgres_test_targets(environ, service_ids=service_ids)
    overlay = {
        item.target.runtime_database_env: item.database_url for item in resolved
    }
    vector_url = environ.get(CX_VECTOR_TEST_DATABASE_ENV)
    if vector_url:
        overlay[CX_VECTOR_RUNTIME_DATABASE_ENV] = _validated_postgres_url(
            vector_url,
            failure_code="cx_vector_test_database_url_invalid",
        )[0]
    return overlay


def postgres_test_targets_public_projection(
    resolved: Iterable[ResolvedPostgresTestTarget],
) -> dict[str, Any]:
    records = tuple(resolved)
    return {
        "schema_version": "platform_postgres_test_targets.v1",
        "profile": "test",
        "service_count": len(records),
        "targets": [
            {
                "service_id": item.target.service_id,
                "test_database_env": item.target.test_database_env,
                "runtime_database_env": item.target.runtime_database_env,
                "expected_database_name": item.target.expected_database_name,
                "expected_role_name": item.target.expected_role_name,
                "drivername": item.drivername,
            }
            for item in records
        ],
        "database_urls_exposed": False,
    }


def service_ids_for_test_database_environments(
    environment_names: Iterable[str],
) -> tuple[str, ...]:
    requested = set(environment_names)
    return tuple(
        item.service_id
        for item in POSTGRES_TEST_TARGETS
        if item.test_database_env in requested
    )


def _resolve_target(
    target: PostgresTestTarget,
    environ: Mapping[str, str],
) -> ResolvedPostgresTestTarget:
    try:
        database_url = required_database_url(target.test_database_env, environ)
    except ValueError as exc:
        raise PostgresTargetConfigError("test_database_url_missing_or_placeholder") from exc
    normalized, drivername, database_name, role_name = _validated_postgres_url(
        database_url,
        failure_code="test_database_url_invalid",
    )
    if database_name != target.expected_database_name:
        raise PostgresTargetConfigError("test_database_name_mismatch")
    if role_name != target.expected_role_name:
        raise PostgresTargetConfigError("test_database_role_mismatch")
    return ResolvedPostgresTestTarget(target, normalized, drivername)


def _validated_postgres_url(
    database_url: str,
    *,
    failure_code: str,
) -> tuple[str, str, str | None, str | None]:
    if is_placeholder_database_url(database_url):
        raise PostgresTargetConfigError(failure_code)
    try:
        parsed = make_url(database_url)
    except SQLAlchemyError as exc:
        raise PostgresTargetConfigError(failure_code) from exc
    if not parsed.drivername.startswith("postgresql"):
        raise PostgresTargetConfigError(failure_code)
    return database_url, parsed.drivername, parsed.database, parsed.username
