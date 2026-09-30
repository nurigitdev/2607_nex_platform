#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_api import register_catalog_lifecycle_routes  # noqa: E402
from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import (  # noqa: E402
    CatalogLifecycleService,
    CatalogLifecycleServiceError,
    RegisterCatalogEntry,
)
from nex_mo.catalog_route_source import CatalogProviderRouteSource  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import run_service_migrations  # noqa: E402


SCHEMA_VERSION = "mo_catalog_lifecycle_postgres_smoke.v1"
ACTIVATION_ENV = "NEX_MO_CATALOG_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_MO_CATALOG_POSTGRES_SMOKE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
SERVICE_ID = "nex-mo"

Exercise = Callable[[str], Mapping[str, Any]]


def run_mo_catalog_lifecycle_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    exercise: Exercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1180",
            "requirement": "S118",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", {"expected_profile": DEFAULT_PROFILE})
    database_url = str(env.get(DATABASE_ENV) or "").strip()
    if not database_url:
        return _failure("configuration_invalid", {"missing_env": [DATABASE_ENV]})
    if _database_target(database_url) != {
        "backend": "postgresql",
        "database_name": EXPECTED_DATABASE,
        "database_user": EXPECTED_ROLE,
    }:
        return _failure(
            "database_target_not_allowed",
            {"expected_database": EXPECTED_DATABASE, "expected_role": EXPECTED_ROLE},
        )

    try:
        observations = dict((exercise or _exercise_postgres)(database_url))
        migration = _mapping(observations.get("migration"))
        cleanup = _mapping(observations.get("cleanup"))
        checks = {
            "actual_test_database_identity": observations.get("database_identity")
            == {"database_name": EXPECTED_DATABASE, "database_user": EXPECTED_ROLE},
            "migrations_current": observations.get("migrations_current") is True,
            "catalog_tables_present": observations.get("catalog_tables_present")
            is True,
            "candidate_catalog_rows_persisted": observations.get("catalog_row_count")
            == 2,
            "append_only_alias_history_persisted": observations.get(
                "binding_row_count"
            )
            == 3,
            "stale_revision_rejected": observations.get("stale_error_code")
            == "MO_ALIAS_REVISION_CONFLICT",
            "fresh_engine_restart_recovered": observations.get("restart_recovered")
            is True,
            "runtime_resolver_selected_active_alias": observations.get(
                "resolved_revision"
            )
            == "s118-candidate-b",
            "rollback_restored_prior_catalog": observations.get(
                "rollback_catalog_restored"
            )
            is True,
            "unauthorized_api_rejected": observations.get("unauthorized_status")
            == 401,
            "authenticated_api_read_succeeded": observations.get("api_status")
            == 200,
            "api_projection_redacted": observations.get("api_redacted") is True,
            "targeted_cleanup_complete": cleanup.get("residue") == 0
            and cleanup.get("deleted_bindings") == 3
            and cleanup.get("deleted_catalog_entries") == 2,
        }
        passed = all(checks.values())
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1180",
            "requirement": "S118",
            "status": "PASS" if passed else "FAIL",
            "failure_code": (
                None if passed else "mo_catalog_lifecycle_postgres_smoke_failed"
            ),
            "service_id": SERVICE_ID,
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "database_identity": observations.get("database_identity"),
            "migration": migration,
            "checks": checks,
            "summary": {
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
                "planned_migration_count": _nonnegative_int(
                    migration.get("planned_count")
                ),
                "applied_migration_count": _nonnegative_int(
                    migration.get("applied_count")
                ),
                "skipped_migration_count": _nonnegative_int(
                    migration.get("skipped_count")
                ),
                "catalog_mutation_count": 7,
                "api_request_count": 2,
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "database_password",
                    "authorization_token",
                    "changed_by",
                    "provider_endpoint",
                    "provider_api_key",
                    "model_path",
                ],
            },
            "next_slice": "1181" if passed else "blocked",
        }
        assert_evidence_redacted(evidence, database_url)
        return evidence
    except Exception as exc:
        failure = _failure(
            "postgres_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(failure, database_url)
        return failure


def _exercise_postgres(database_url: str) -> dict[str, Any]:
    migration_result = run_service_migrations(
        SERVICE_ID,
        database_url=database_url,
        profile="test",
    )
    migration = {
        "planned_count": len(migration_result.planned),
        "applied_count": len(migration_result.applied),
        "skipped_count": len(migration_result.skipped),
        "profile": migration_result.profile,
    }
    suffix = uuid4().hex
    alias = f"s118-smoke-{suffix}"
    catalog_ids = [f"catalog:s118-{suffix}-a", f"catalog:s118-{suffix}-b"]
    first_ids = iter(
        (
            f"s118-{suffix}-a",
            f"s118-{suffix}-b",
            f"s118-{suffix}-binding-a",
            f"s118-{suffix}-binding-b",
        )
    )
    first_engine: Engine | None = None
    restarted_engine: Engine | None = None
    cleanup = {
        "deleted_bindings": 0,
        "deleted_catalog_entries": 0,
        "residue": -1,
    }
    cleanup_done = False
    try:
        first_engine = build_engine(database_url)
        first_factory = build_session_factory(first_engine)
        first_repository = SqlAlchemyCatalogLifecycleRepository(first_factory)
        service = CatalogLifecycleService(
            first_repository,
            clock=lambda: "2026-10-01T06:00:00Z",
            id_factory=lambda: next(first_ids),
        )
        service.ensure_bootstrap()
        _cleanup_rows(first_engine, alias, catalog_ids)
        candidate_a = _register_active_candidate(
            service,
            revision="s118-candidate-a",
            deployment=f"s118-{suffix}-a",
        )
        candidate_b = _register_active_candidate(
            service,
            revision="s118-candidate-b",
            deployment=f"s118-{suffix}-b",
        )
        first = service.activate_alias(
            alias=alias,
            capability="generation",
            catalog_id=candidate_a.catalog_id,
            expected_binding_revision=0,
            change_reason="S118 PostgreSQL smoke candidate A",
            changed_by="service:nex-ag",
        )
        second = service.activate_alias(
            alias=alias,
            capability="generation",
            catalog_id=candidate_b.catalog_id,
            expected_binding_revision=first.binding_revision,
            change_reason="S118 PostgreSQL smoke candidate B",
            changed_by="service:nex-ag",
        )

        first_engine.dispose()
        first_engine = None
        restarted_engine = build_engine(database_url)
        restarted_factory = build_session_factory(restarted_engine)
        restarted_repository = SqlAlchemyCatalogLifecycleRepository(restarted_factory)
        restarted_service = CatalogLifecycleService(
            restarted_repository,
            clock=lambda: "2026-10-01T06:05:00Z",
            id_factory=lambda: f"s118-{suffix}-rollback",
        )
        recovered = restarted_service.list_alias_bindings(
            alias=alias,
            capability="generation",
        )
        resolved = next(
            route
            for route in CatalogProviderRouteSource(restarted_service)()
            if route.alias == alias
        )
        try:
            restarted_service.activate_alias(
                alias=alias,
                capability="generation",
                catalog_id=candidate_a.catalog_id,
                expected_binding_revision=1,
                change_reason="Expected stale conflict",
                changed_by="service:nex-ag",
            )
            stale_error_code = None
        except CatalogLifecycleServiceError as exc:
            stale_error_code = exc.error_code
        rollback = restarted_service.rollback_alias(
            alias=alias,
            capability="generation",
            expected_binding_revision=second.binding_revision,
            change_reason="S118 PostgreSQL smoke rollback",
            changed_by="service:nex-ag",
        )

        app = FastAPI()
        register_catalog_lifecycle_routes(app, service=restarted_service)
        client = TestClient(app)
        unauthorized = client.get(
            "/api/v1/provider-alias-bindings",
            params={"alias": alias},
        )
        token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
        response = client.get(
            "/api/v1/provider-alias-bindings",
            params={"alias": alias},
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        payload = _json_object(response.json())
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        api_redacted = not any(
            field in serialized
            for field in (
                "changed_by",
                "provider_endpoint",
                "provider_api_key",
                "model_path",
                "database_url",
            )
        )

        with restarted_engine.connect() as connection:
            database_name, database_user = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            migration_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = ANY(:versions)"
                    ),
                    {"versions": list(migration_result.planned)},
                ).scalar_one()
            )
            table_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM (VALUES "
                        "(to_regclass('public.mo_model_catalog')), "
                        "(to_regclass('public.mo_alias_bindings'))) AS tables(name) "
                        "WHERE name IS NOT NULL"
                    )
                ).scalar_one()
            )
            catalog_row_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM mo_model_catalog "
                        "WHERE catalog_id = ANY(:catalog_ids)"
                    ),
                    {"catalog_ids": catalog_ids},
                ).scalar_one()
            )
            binding_row_count = int(
                connection.execute(
                    text("SELECT count(*) FROM mo_alias_bindings WHERE alias = :alias"),
                    {"alias": alias},
                ).scalar_one()
            )

        cleanup = _cleanup_rows(restarted_engine, alias, catalog_ids)
        cleanup_done = True
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": migration,
            "migrations_current": migration_count == len(migration_result.planned),
            "catalog_tables_present": table_count == 2,
            "catalog_row_count": catalog_row_count,
            "binding_row_count": binding_row_count,
            "stale_error_code": stale_error_code,
            "restart_recovered": len(recovered) == 2
            and recovered[-1].catalog_id == candidate_b.catalog_id,
            "resolved_revision": resolved.model_revision,
            "rollback_catalog_restored": rollback.catalog_id == candidate_a.catalog_id
            and rollback.binding_revision == 3,
            "unauthorized_status": unauthorized.status_code,
            "api_status": response.status_code,
            "api_redacted": api_redacted,
            "cleanup": cleanup,
        }
    finally:
        cleanup_engine = restarted_engine or first_engine
        if cleanup_engine is not None and not cleanup_done:
            _cleanup_rows(cleanup_engine, alias, catalog_ids)
        if restarted_engine is not None:
            restarted_engine.dispose()
        if first_engine is not None:
            first_engine.dispose()


def _register_active_candidate(
    service: CatalogLifecycleService,
    *,
    revision: str,
    deployment: str,
):
    entry = service.register_catalog_entry(
        RegisterCatalogEntry(
            provider_capability="generation",
            model_name="S118 PostgreSQL candidate",
            model_revision=revision,
            deployment_id=deployment,
            runtime_profile="s118-postgres-smoke",
            precision="BF16",
            provider_type="openai-compatible",
            supports_response_formats=("text", "json_object"),
            max_input_tokens=8192,
            max_output_tokens=1024,
        )
    )
    return service.transition_catalog_entry(
        entry.catalog_id,
        expected_revision=1,
        target_state="ACTIVE",
    )


def _cleanup_rows(
    engine: Engine,
    alias: str,
    catalog_ids: list[str],
) -> dict[str, int]:
    with engine.begin() as connection:
        bindings = connection.execute(
            text("DELETE FROM mo_alias_bindings WHERE alias = :alias"),
            {"alias": alias},
        )
        entries = connection.execute(
            text("DELETE FROM mo_model_catalog WHERE catalog_id = ANY(:catalog_ids)"),
            {"catalog_ids": catalog_ids},
        )
        residue = int(
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM mo_alias_bindings WHERE alias = :alias) + "
                    "(SELECT count(*) FROM mo_model_catalog "
                    " WHERE catalog_id = ANY(:catalog_ids))"
                ),
                {"alias": alias, "catalog_ids": catalog_ids},
            ).scalar_one()
        )
    return {
        "deleted_bindings": int(bindings.rowcount or 0),
        "deleted_catalog_entries": int(entries.rowcount or 0),
        "residue": residue,
    }


def _database_target(database_url: str) -> dict[str, str | None]:
    try:
        parsed = make_url(database_url)
    except Exception:
        return {"backend": None, "database_name": None, "database_user": None}
    return {
        "backend": parsed.get_backend_name(),
        "database_name": parsed.database,
        "database_user": parsed.username,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("response_not_json_object")
    return dict(value)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _failure(
    failure_code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1180",
        "requirement": "S118",
        "status": "FAIL",
        "failure_code": failure_code,
        "issues": [failure_code],
        "next_slice": "blocked",
    }
    if diagnostics:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def assert_evidence_redacted(evidence: Mapping[str, Any], database_url: str) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected = [database_url]
    try:
        protected.append(str(make_url(database_url).password or ""))
    except Exception:
        pass
    if any(value and len(value) >= 6 and value in serialized for value in protected):
        raise ValueError("MO catalog PostgreSQL evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "mo_catalog_lifecycle_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"migrations={summary.get('applied_migration_count', 0)}+"
        f"{summary.get('skipped_migration_count', 0)}/"
        f"{summary.get('planned_migration_count', 0)} "
        f"mutations={summary.get('catalog_mutation_count', 0)} "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_catalog_lifecycle_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
