#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch
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

import nex_mo.remote_provider as remote_provider  # noqa: E402
from nex_mo.provider_registry import ProviderRouteError  # noqa: E402
from nex_mo.provider_retry import ProviderRetryEvent  # noqa: E402
from nex_mo.provider_telemetry_persistence import (  # noqa: E402
    ProviderTelemetryIdentity,
)
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402
from nex_mo.providers import register_mock_provider_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import run_service_migrations  # noqa: E402


SCHEMA_VERSION = "mo_provider_telemetry_postgres_smoke.v1"
ACTIVATION_ENV = "NEX_MO_PROVIDER_TELEMETRY_POSTGRES_SMOKE"
PROFILE_ENV = "NEX_MO_PROVIDER_TELEMETRY_POSTGRES_SMOKE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
SERVICE_ID = "nex-mo"
MUTATION_COUNT = 24
WORKER_COUNT = 8

Exercise = Callable[[str], Mapping[str, Any]]


def run_mo_provider_telemetry_postgres_smoke(
    environ: Mapping[str, str] | None = None,
    *,
    exercise: Exercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1160",
            "requirement": "S116",
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
            {
                "expected_database": EXPECTED_DATABASE,
                "expected_role": EXPECTED_ROLE,
            },
        )

    try:
        observations = dict((exercise or _exercise_postgres)(database_url))
        cleanup = _mapping(observations.get("cleanup"))
        counts = _mapping(observations.get("counts"))
        migration = _mapping(observations.get("migration"))
        checks = {
            "actual_test_database_identity": observations.get("database_identity")
            == {"database_name": EXPECTED_DATABASE, "database_user": EXPECTED_ROLE},
            "migrations_current": observations.get("migrations_current") is True,
            "telemetry_table_present": observations.get("telemetry_table_present")
            is True,
            "atomic_concurrent_counts_exact": counts
            == {
                "request_count": MUTATION_COUNT,
                "success_count": MUTATION_COUNT // 2,
                "failure_count": MUTATION_COUNT // 2,
                "retryable_failure_count": MUTATION_COUNT // 2,
                "degraded_count": MUTATION_COUNT // 2,
                "attempt_count": MUTATION_COUNT + 1,
                "retry_count": 1,
            },
            "fresh_engine_restart_recovered": observations.get("restart_recovered")
            is True,
            "latest_diagnostics_monotonic": observations.get("latest_observed_at")
            == "2026-09-30T12:00:24Z"
            and observations.get("latest_outcome") == "success",
            "unauthorized_api_rejected": observations.get("unauthorized_status") == 401,
            "authenticated_api_read_succeeded": observations.get("api_status") == 200,
            "api_projection_matches_durable_counts": observations.get(
                "api_counts_match"
            )
            is True,
            "api_projection_redacted": observations.get("api_redacted") is True,
            "targeted_cleanup_complete": cleanup
            == {"deleted_count": 1, "residue": 0},
        }
        passed = all(checks.values())
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1160",
            "requirement": "S116",
            "status": "PASS" if passed else "FAIL",
            "failure_code": (
                None if passed else "mo_provider_telemetry_postgres_smoke_failed"
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
                "worker_count": WORKER_COUNT,
                "mutation_count": MUTATION_COUNT + 1,
                "request_count": _nonnegative_int(counts.get("request_count")),
                "attempt_count": _nonnegative_int(counts.get("attempt_count")),
                "api_request_count": 2,
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "database_password",
                    "authorization_token",
                    "provider_endpoint",
                    "provider_api_key",
                    "telemetry_key",
                ],
            },
            "next_slice": "1161" if passed else "blocked",
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
    effective_env = {
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://telemetry-smoke.invalid/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": f"s116-private-{suffix}",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "S116-Smoke-Embedding",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "s116-smoke-revision",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": f"s116-smoke-{suffix}",
    }
    config = remote_provider.build_remote_embedding_execution_config(effective_env)
    telemetry_key = config.capability
    first_engine: Engine | None = None
    restarted_engine: Engine | None = None
    cleanup = {"deleted_count": 0, "residue": -1}
    cleanup_done = False
    prior_store = remote_provider.current_remote_provider_telemetry_store()
    try:
        first_engine = build_engine(database_url)
        first_factory = build_session_factory(first_engine)
        first_repository = SqlAlchemyDurableProviderTelemetryRepository(first_factory)
        first_store = DurableProviderTelemetryStore(first_repository)
        identity = ProviderTelemetryIdentity.from_config(config)
        telemetry_key = identity.storage_key()
        _cleanup_telemetry(first_engine, telemetry_key)

        first_store.record_retry(
            config,
            event=ProviderRetryEvent(
                capability="embedding",
                attempt_number=1,
                next_attempt_number=2,
                delay_seconds=0.25,
                failure_kind="upstream_5xx",
                reason="transient_failure_within_budget",
            ),
            observed_at="2026-09-30T12:00:00Z",
        )

        def record(index: int) -> None:
            observed_at = f"2026-09-30T12:00:{index:02d}Z"
            if index % 2 == 0:
                first_store.record_success(
                    config,
                    latency_ms=10 + index,
                    observed_at=observed_at,
                )
                return
            first_store.record_failure(
                config,
                route_error=ProviderRouteError(
                    status_code=503,
                    error_code="mo.remote_embedding.http_error",
                    detail="smoke failure detail is not persisted",
                    retryable=True,
                    degraded=True,
                    failure_kind="upstream_5xx",
                    upstream_status_code=503,
                ),
                latency_ms=10 + index,
                observed_at=observed_at,
            )

        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
            list(executor.map(record, range(1, MUTATION_COUNT + 1)))

        first_engine.dispose()
        first_engine = None
        restarted_engine = build_engine(database_url)
        restarted_factory = build_session_factory(restarted_engine)
        restarted_repository = SqlAlchemyDurableProviderTelemetryRepository(
            restarted_factory
        )
        restarted_store = DurableProviderTelemetryStore(restarted_repository)
        records = restarted_repository.list_records(capability="embedding")
        record_by_key = {
            record.identity.storage_key(): record for record in records
        }.get(telemetry_key)
        if record_by_key is None:
            raise RuntimeError("restarted telemetry record was not found")

        counts = {
            "request_count": record_by_key.request_count,
            "success_count": record_by_key.success_count,
            "failure_count": record_by_key.failure_count,
            "retryable_failure_count": record_by_key.retryable_failure_count,
            "degraded_count": record_by_key.degraded_count,
            "attempt_count": record_by_key.attempt_count,
            "retry_count": record_by_key.retry_count,
        }
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
            table_present = (
                connection.execute(
                    text("SELECT to_regclass('public.mo_provider_telemetry')")
                ).scalar_one()
                == "mo_provider_telemetry"
            )

        remote_provider.configure_remote_provider_telemetry_store(restarted_store)
        app = FastAPI()
        register_mock_provider_routes(app)
        token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
        with patch.dict(os.environ, effective_env, clear=False):
            client = TestClient(app)
            unauthorized = client.get(
                "/api/v1/provider-telemetry",
                params={"capability": "embedding"},
            )
            response = client.get(
                "/api/v1/provider-telemetry",
                params={"capability": "embedding"},
                headers={"Authorization": f"Bearer {token.access_token}"},
            )
        payload = _json_object(response.json())
        data = payload.get("data")
        item = data[0] if isinstance(data, list) and len(data) == 1 else {}
        private_values = (
            effective_env["NEX_MO_REMOTE_EMBEDDING_URL"],
            effective_env["NEX_MO_REMOTE_EMBEDDING_API_KEY"],
        )
        serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        api_counts_match = all(item.get(key) == value for key, value in counts.items())
        api_redacted = not any(value in serialized_payload for value in private_values)

        cleanup = _cleanup_telemetry(restarted_engine, telemetry_key)
        cleanup_done = True
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": migration,
            "migrations_current": migration_count == len(migration_result.planned),
            "telemetry_table_present": table_present,
            "counts": counts,
            "restart_recovered": record_by_key.identity.storage_key() == telemetry_key,
            "latest_observed_at": record_by_key.last_observed_at,
            "latest_outcome": record_by_key.last_outcome,
            "unauthorized_status": unauthorized.status_code,
            "api_status": response.status_code,
            "api_counts_match": api_counts_match,
            "api_redacted": api_redacted,
            "cleanup": cleanup,
        }
    finally:
        remote_provider.configure_remote_provider_telemetry_store(prior_store)
        cleanup_engine = restarted_engine or first_engine
        if cleanup_engine is not None and not cleanup_done:
            _cleanup_telemetry(cleanup_engine, telemetry_key)
        if restarted_engine is not None:
            restarted_engine.dispose()
        if first_engine is not None:
            first_engine.dispose()


def _cleanup_telemetry(engine: Engine, telemetry_key: str) -> dict[str, int]:
    with engine.begin() as connection:
        result = connection.execute(
            text("DELETE FROM mo_provider_telemetry WHERE telemetry_key = :key"),
            {"key": telemetry_key},
        )
        residue = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM mo_provider_telemetry "
                    "WHERE telemetry_key = :key"
                ),
                {"key": telemetry_key},
            ).scalar_one()
        )
    return {"deleted_count": int(result.rowcount or 0), "residue": residue}


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
        "slice": "1160",
        "requirement": "S116",
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
        raise ValueError("MO telemetry PostgreSQL evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "mo_provider_telemetry_postgres_smoke="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"migrations={summary.get('applied_migration_count', 0)}+"
        f"{summary.get('skipped_migration_count', 0)}/"
        f"{summary.get('planned_migration_count', 0)} "
        f"mutations={summary.get('mutation_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
