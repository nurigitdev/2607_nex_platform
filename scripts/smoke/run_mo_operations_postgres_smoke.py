#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_repository import (  # noqa: E402
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import CatalogLifecycleService  # noqa: E402
from nex_mo.operations_api import register_operations_routes  # noqa: E402
from nex_mo.operations_service import MOOperationsService  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.provider_telemetry_persistence import ProviderTelemetryIdentity  # noqa: E402
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_reranker_execution_config,
)
from nex_mo.runtime_observability_service import RuntimeObservabilityService  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import run_service_migrations  # noqa: E402


SCHEMA_VERSION = "mo_operations_postgres_smoke.v1"
ACTIVATION_ENV = "NEX_MO_OPERATIONS_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_MO_OPERATIONS_POSTGRES_SMOKE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
SERVICE_ID = "nex-mo"
NOW = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)

Exercise = Callable[[str], Mapping[str, Any]]


def run_mo_operations_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    exercise: Exercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1189",
            "requirement": "S119",
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
            "operations_tables_present": observations.get("table_count") == 3,
            "bootstrap_aliases_durable": observations.get("active_alias_count") == 3,
            "telemetry_rows_persisted": observations.get("telemetry_row_count") == 3,
            "telemetry_events_persisted": observations.get("telemetry_request_count")
            == 3,
            "fresh_engine_restart_recovered": observations.get("restart_recovered")
            is True,
            "unauthorized_api_rejected": observations.get("unauthorized_status")
            == 401,
            "authenticated_api_read_succeeded": observations.get("api_status") == 200,
            "operations_snapshot_ready": observations.get("operations_status")
            == "READY",
            "all_sources_ready": observations.get("ready_source_count") == 4,
            "all_capabilities_ready": observations.get("ready_capability_count") == 3,
            "durable_counters_projected": observations.get("projected_request_count")
            == 3,
            "canonical_schema_valid": observations.get("schema_error_count") == 0,
            "api_projection_redacted": observations.get("api_redacted") is True,
            "targeted_cleanup_complete": cleanup.get("residue") == 0
            and cleanup.get("deleted_telemetry_rows") == 3,
        }
        passed = all(checks.values())
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1189",
            "requirement": "S119",
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "mo_operations_postgres_smoke_failed",
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
                "persisted_telemetry_count": _nonnegative_int(
                    observations.get("telemetry_row_count")
                ),
                "ready_source_count": _nonnegative_int(
                    observations.get("ready_source_count")
                ),
                "ready_capability_count": _nonnegative_int(
                    observations.get("ready_capability_count")
                ),
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "database_password",
                    "authorization_token",
                    "provider_endpoint",
                    "provider_api_key",
                    "ssh_target",
                ],
            },
            "next_slice": "1190" if passed else "blocked",
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
    base_configs = (
        build_remote_embedding_execution_config({}),
        build_remote_reranker_execution_config({}),
        build_remote_generation_execution_config({}),
    )
    configs = tuple(
        replace(config, deployment_id=f"s119-{suffix}-{config.capability}")
        for config in base_configs
    )
    telemetry_keys = [
        ProviderTelemetryIdentity.from_config(config).storage_key()
        for config in configs
    ]
    first_engine: Engine | None = None
    restarted_engine: Engine | None = None
    cleanup = {"deleted_telemetry_rows": 0, "residue": -1}
    cleanup_done = False
    try:
        first_engine = build_engine(database_url)
        _cleanup_telemetry(first_engine, telemetry_keys)
        first_factory = build_session_factory(first_engine)
        catalog = CatalogLifecycleService(
            SqlAlchemyCatalogLifecycleRepository(first_factory),
            clock=lambda: "2026-10-01T07:00:00Z",
        )
        catalog.ensure_bootstrap()
        telemetry = DurableProviderTelemetryStore(
            SqlAlchemyDurableProviderTelemetryRepository(first_factory)
        )
        for offset, config in enumerate(configs, start=1):
            telemetry.record_success(
                config,
                latency_ms=offset * 10,
                observed_at=f"2026-10-01T07:00:0{offset}Z",
            )

        first_engine.dispose()
        first_engine = None
        restarted_engine = build_engine(database_url)
        restarted_factory = build_session_factory(restarted_engine)
        restarted_catalog = CatalogLifecycleService(
            SqlAlchemyCatalogLifecycleRepository(restarted_factory),
            clock=lambda: "2026-10-01T07:05:00Z",
        )
        restarted_telemetry = DurableProviderTelemetryStore(
            SqlAlchemyDurableProviderTelemetryRepository(restarted_factory)
        )
        recovered_telemetry = restarted_telemetry.snapshot(configs)
        operations = MOOperationsService(
            catalog_service=restarted_catalog,
            readiness_service=ProviderReadinessService(environ={}, now=lambda: NOW),
            runtime_service=RuntimeObservabilityService(environ={}, now=lambda: NOW),
            telemetry_reader=lambda: restarted_telemetry.snapshot(configs),
            environ={},
            now=lambda: NOW,
        )
        app = FastAPI()
        register_operations_routes(app, service=operations)
        client = TestClient(app)
        unauthorized = client.get("/api/v1/operations-snapshot")
        token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
        response = client.get(
            "/api/v1/operations-snapshot?force_refresh=true",
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        payload = _json_object(response.json())
        schema = _read_json(ROOT / "contracts/schemas/service/nex_mo/operations_snapshot.v1.schema.json")
        schema_errors = list(Draft202012Validator(schema).iter_errors(payload))
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
        sources = payload.get("sources", [])
        capabilities = payload.get("capabilities", [])

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
                        "(to_regclass('public.mo_alias_bindings')), "
                        "(to_regclass('public.mo_provider_telemetry'))) AS tables(name) "
                        "WHERE name IS NOT NULL"
                    )
                ).scalar_one()
            )
            telemetry_row_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM mo_provider_telemetry "
                        "WHERE telemetry_key = ANY(:keys)"
                    ),
                    {"keys": telemetry_keys},
                ).scalar_one()
            )
            telemetry_request_count = int(
                connection.execute(
                    text(
                        "SELECT coalesce(sum(request_count), 0) "
                        "FROM mo_provider_telemetry "
                        "WHERE telemetry_key = ANY(:keys)"
                    ),
                    {"keys": telemetry_keys},
                ).scalar_one()
            )

        cleanup = _cleanup_telemetry(restarted_engine, telemetry_keys)
        cleanup_done = True
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": migration,
            "migrations_current": migration_count == len(migration_result.planned),
            "table_count": table_count,
            "active_alias_count": len(
                restarted_catalog.list_alias_bindings(state="ACTIVE")
            ),
            "telemetry_row_count": telemetry_row_count,
            "telemetry_request_count": telemetry_request_count,
            "restart_recovered": len(recovered_telemetry) == 3
            and all(item.get("request_count") == 1 for item in recovered_telemetry),
            "unauthorized_status": unauthorized.status_code,
            "api_status": response.status_code,
            "operations_status": payload.get("operations_status"),
            "ready_source_count": sum(
                isinstance(item, Mapping) and item.get("status") == "READY"
                for item in sources
            ),
            "ready_capability_count": sum(
                isinstance(item, Mapping)
                and item.get("operations_status") == "READY"
                for item in capabilities
            ),
            "projected_request_count": sum(
                int(item.get("request_count", 0))
                for item in capabilities
                if isinstance(item, Mapping)
            ),
            "schema_error_count": len(schema_errors),
            "api_redacted": not any(
                field in serialized
                for field in (
                    "api_key",
                    "authorization",
                    "database_url",
                    "password",
                    "provider_endpoint",
                    "ssh_target",
                )
            ),
            "cleanup": cleanup,
        }
    finally:
        cleanup_engine = restarted_engine or first_engine
        if cleanup_engine is not None and not cleanup_done:
            _cleanup_telemetry(cleanup_engine, telemetry_keys)
        if restarted_engine is not None:
            restarted_engine.dispose()
        if first_engine is not None:
            first_engine.dispose()


def _cleanup_telemetry(engine: Engine, keys: list[str]) -> dict[str, int]:
    with engine.begin() as connection:
        deleted = connection.execute(
            text("DELETE FROM mo_provider_telemetry WHERE telemetry_key = ANY(:keys)"),
            {"keys": keys},
        )
        residue = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM mo_provider_telemetry "
                    "WHERE telemetry_key = ANY(:keys)"
                ),
                {"keys": keys},
            ).scalar_one()
        )
    return {
        "deleted_telemetry_rows": int(deleted.rowcount or 0),
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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


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
        "slice": "1189",
        "requirement": "S119",
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
        raise ValueError("MO operations PostgreSQL evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "mo_operations_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"migrations={summary.get('applied_migration_count', 0)}+"
        f"{summary.get('skipped_migration_count', 0)}/"
        f"{summary.get('planned_migration_count', 0)} "
        f"telemetry={summary.get('persisted_telemetry_count', 0)} "
        f"ready={summary.get('ready_source_count', 0)}/4+"
        f"{summary.get('ready_capability_count', 0)}/3 "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
