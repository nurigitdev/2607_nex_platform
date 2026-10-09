#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
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
from nex_mo.operations_acceptance import build_operations_acceptance_plan  # noqa: E402
from nex_mo.operations_api import register_operations_routes  # noqa: E402
from nex_mo.operations_service import MOOperationsService  # noqa: E402
from nex_mo.provider_readiness_service import ProviderReadinessService  # noqa: E402
from nex_mo.provider_telemetry_persistence import ProviderTelemetryIdentity  # noqa: E402
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)
from nex_mo.provider_telemetry_runtime import (  # noqa: E402
    configure_remote_provider_telemetry_store,
    current_remote_provider_telemetry_store,
)
from nex_mo.provider_telemetry_store import DurableProviderTelemetryStore  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_embedding_execution_config,
    build_remote_generation_execution_config,
    build_remote_reranker_execution_config,
    execute_remote_embedding_request,
    execute_remote_generation_request,
    execute_remote_rerank_request,
)
from nex_mo.runtime_observability_service import RuntimeObservabilityService  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_engine,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import run_service_migrations  # noqa: E402


SCHEMA_VERSION = "mo_operations_live_acceptance.v1"
GENERATION_REASONING_MODE = "disabled"
ACTIVATION_ENV = "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE"
PROFILE_ENV = "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
SERVICE_ID = "nex-mo"
NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
PROTECTED_ENV_KEYS = (
    DATABASE_ENV,
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_DGX_SSH_TARGET",
)

Exercise = Callable[[str, dict[str, str]], Mapping[str, Any]]


def run_mo_operations_live_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    exercise: Exercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1190",
            "requirement": "S119",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed", {"expected_profile": DEFAULT_PROFILE})
    database_url = str(env.get(DATABASE_ENV) or "").strip()
    plan = build_operations_acceptance_plan(env)
    if plan.admission_status != "READY":
        return _failure(
            "live_acceptance_not_admitted",
            {"issues": list(plan.issues)},
        )

    try:
        observations = dict((exercise or _exercise_live)(database_url, env))
        migration = _mapping(observations.get("migration"))
        cleanup = _mapping(observations.get("cleanup"))
        checks = {
            "actual_test_database_identity": observations.get("database_identity")
            == {"database_name": EXPECTED_DATABASE, "database_user": EXPECTED_ROLE},
            "migrations_current": observations.get("migrations_current") is True,
            "all_live_provider_requests_succeeded": observations.get(
                "provider_success_count"
            )
            == 3,
            "expected_models_returned": observations.get("model_match_count") == 3,
            "durable_live_telemetry_persisted": observations.get(
                "telemetry_row_count"
            )
            == 3
            and observations.get("telemetry_request_count") == 3,
            "authenticated_operations_api_succeeded": observations.get("api_status")
            == 200,
            "live_operations_snapshot_ready": observations.get("operations_status")
            == "READY"
            and observations.get("provider_mode") == "live",
            "all_live_sources_ready": observations.get("ready_source_count") == 4,
            "all_live_capabilities_ready": observations.get(
                "ready_capability_count"
            )
            == 3,
            "all_runtime_models_healthy": observations.get(
                "runtime_ready_capability_count"
            )
            == 3,
            "canonical_schema_valid": observations.get("schema_error_count") == 0,
            "api_projection_redacted": observations.get("api_redacted") is True,
            "targeted_cleanup_complete": cleanup.get("residue") == 0
            and cleanup.get("deleted_telemetry_rows") == 3,
        }
        passed = all(checks.values())
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1190",
            "requirement": "S119",
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "mo_operations_live_acceptance_failed",
            "service_id": SERVICE_ID,
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "database_identity": observations.get("database_identity"),
            "migration": migration,
            "checks": checks,
            "summary": {
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
                "provider_success_count": _nonnegative_int(
                    observations.get("provider_success_count")
                ),
                "model_match_count": _nonnegative_int(
                    observations.get("model_match_count")
                ),
                "telemetry_row_count": _nonnegative_int(
                    observations.get("telemetry_row_count")
                ),
                "ready_source_count": _nonnegative_int(
                    observations.get("ready_source_count")
                ),
                "ready_capability_count": _nonnegative_int(
                    observations.get("ready_capability_count")
                ),
                "runtime_ready_capability_count": _nonnegative_int(
                    observations.get("runtime_ready_capability_count")
                ),
                "schema_error_count": _nonnegative_int(
                    observations.get("schema_error_count")
                ),
                "generation_reasoning_mode": GENERATION_REASONING_MODE,
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "provider_endpoints",
                    "provider_api_keys",
                    "database_password",
                    "authorization_token",
                    "ssh_target",
                    "raw_provider_payloads",
                    "process_commands",
                ],
            },
            "next_slice": "1191" if passed else "blocked",
        }
        assert_evidence_redacted(evidence, env)
        return evidence
    except Exception as exc:
        failure = _failure(
            "live_acceptance_execution_failed",
            {"exception_type": exc.__class__.__name__},
        )
        assert_evidence_redacted(failure, env)
        return failure


def _exercise_live(database_url: str, environment: dict[str, str]) -> dict[str, Any]:
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
    env = {
        **environment,
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": f"s119-{suffix}-embedding",
        "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": f"s119-{suffix}-reranking",
        "NEX_MO_VLLM_DEPLOYMENT_ID": f"s119-{suffix}-generation",
    }
    configs = (
        build_remote_embedding_execution_config(env),
        build_remote_reranker_execution_config(env),
        build_remote_generation_execution_config(env),
    )
    telemetry_keys = [
        ProviderTelemetryIdentity.from_config(config).storage_key()
        for config in configs
    ]
    engine: Engine | None = None
    cleanup = {"deleted_telemetry_rows": 0, "residue": -1}
    cleanup_done = False
    previous_store = current_remote_provider_telemetry_store()
    try:
        engine = build_engine(database_url)
        _cleanup_telemetry(engine, telemetry_keys)
        session_factory = build_session_factory(engine)
        catalog = CatalogLifecycleService(
            SqlAlchemyCatalogLifecycleRepository(session_factory),
            clock=lambda: "2026-10-01T08:00:00Z",
        )
        catalog.ensure_bootstrap()
        telemetry = DurableProviderTelemetryStore(
            SqlAlchemyDurableProviderTelemetryRepository(session_factory)
        )
        configure_remote_provider_telemetry_store(telemetry)

        embedding = execute_remote_embedding_request(
            {
                "alias": "mock-embedding-default",
                "inputs": ["NeX S119 protected live acceptance."],
            },
            environ=env,
        )
        reranking = execute_remote_rerank_request(
            {
                "alias": "mock-reranker-default",
                "query": "protected live acceptance",
                "documents": [
                    "NeX MO provider operations acceptance.",
                    "Unrelated control document.",
                ],
                "top_n": 1,
            },
            environ=env,
        )
        generation = execute_remote_generation_request(
            {
                "alias": "general-llm-default",
                "provider_capability": "generation",
                "prompt": "Return the exact phrase 'NEX S119 OK' and no extra text.",
                "response_format": {"type": "text"},
                "reasoning_mode": GENERATION_REASONING_MODE,
                "max_output_tokens": 32,
                "temperature": 0.0,
            },
            request_id=f"s119-{suffix}",
            trace_id=f"s119-{suffix}",
            environ=env,
        )
        provider_results = (embedding, reranking, generation)

        operations = MOOperationsService(
            catalog_service=catalog,
            readiness_service=ProviderReadinessService(environ=env),
            runtime_service=RuntimeObservabilityService(environ=env),
            telemetry_reader=lambda: telemetry.snapshot(configs),
            environ=env,
        )
        app = FastAPI()
        register_operations_routes(app, service=operations)
        token = issue_mock_service_token(service_id="nex-ag", audience=SERVICE_ID)
        response = TestClient(app).get(
            "/api/v1/operations-snapshot?force_refresh=true",
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        payload = _json_object(response.json())
        schema = _read_json(
            ROOT / "contracts/schemas/service/nex_mo/operations_snapshot.v1.schema.json"
        )
        schema_errors = list(Draft202012Validator(schema).iter_errors(payload))
        sources = payload.get("sources", [])
        capabilities = payload.get("capabilities", [])
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        with engine.connect() as connection:
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

        cleanup = _cleanup_telemetry(engine, telemetry_keys)
        cleanup_done = True
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": migration,
            "migrations_current": migration_count == len(migration_result.planned),
            "provider_success_count": sum(bool(item) for item in provider_results),
            "model_match_count": sum(
                str(result.get("model_revision")) == config.model_revision
                for result, config in zip(provider_results, configs, strict=True)
            ),
            "telemetry_row_count": telemetry_row_count,
            "telemetry_request_count": telemetry_request_count,
            "api_status": response.status_code,
            "operations_status": payload.get("operations_status"),
            "provider_mode": payload.get("provider_mode"),
            "ready_source_count": sum(
                isinstance(item, Mapping) and item.get("status") == "READY"
                for item in sources
            ),
            "ready_capability_count": sum(
                isinstance(item, Mapping)
                and item.get("operations_status") == "READY"
                for item in capabilities
            ),
            "runtime_ready_capability_count": sum(
                isinstance(item, Mapping) and item.get("runtime_status") == "READY"
                for item in capabilities
            ),
            "schema_error_count": len(schema_errors),
            "api_redacted": not any(
                value and len(value) >= 6 and value in serialized
                for key in PROTECTED_ENV_KEYS
                if (value := env.get(key))
            ),
            "cleanup": cleanup,
        }
    finally:
        configure_remote_provider_telemetry_store(previous_store)
        if engine is not None and not cleanup_done:
            _cleanup_telemetry(engine, telemetry_keys)
        if engine is not None:
            engine.dispose()


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
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1190",
        "requirement": "S119",
        "status": "FAIL",
        "failure_code": failure_code,
        "issues": [failure_code],
        "next_slice": "blocked",
    }
    if diagnostics:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected = [str(environ.get(key) or "") for key in PROTECTED_ENV_KEYS]
    database_url = str(environ.get(DATABASE_ENV) or "")
    try:
        protected.append(str(make_url(database_url).password or ""))
    except Exception:
        pass
    if any(value and len(value) >= 6 and value in serialized for value in protected):
        raise ValueError("MO operations live evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"mo_operations_live_acceptance=skipped reason={ACTIVATION_ENV}"
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "mo_operations_live_acceptance="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('provider_success_count', 0)}/3 "
        f"models={summary.get('model_match_count', 0)}/3 "
        f"sources={summary.get('ready_source_count', 0)}/4 "
        f"runtime={summary.get('runtime_ready_capability_count', 0)}/3 "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_operations_live_acceptance()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
