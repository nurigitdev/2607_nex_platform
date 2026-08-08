#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    check_database_readiness,
    load_env_file,
    redact_database_url,
)
from run_ag_cross_service_observability_smoke import (  # noqa: E402
    SMOKE_ENV as AG_OBSERVABILITY_SMOKE_ENV,
    SMOKE_PROFILE_ENV as AG_OBSERVABILITY_PROFILE_ENV,
    run_ag_cross_service_observability_smoke,
)
from run_cx_processing_postgres_event_smoke import (  # noqa: E402
    SMOKE_ENV as CX_PROCESSING_EVENT_SMOKE_ENV,
    SMOKE_PROFILE_ENV as CX_PROCESSING_EVENT_PROFILE_ENV,
    run_cx_processing_postgres_event_smoke,
)
from run_cx_processing_postgres_jobqueue_smoke import (  # noqa: E402
    SMOKE_ENV as CX_PROCESSING_JOBQUEUE_SMOKE_ENV,
    SMOKE_PROFILE_ENV as CX_PROCESSING_JOBQUEUE_PROFILE_ENV,
    run_cx_processing_postgres_jobqueue_smoke,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)
from run_postgres_jobqueue_smoke import (  # noqa: E402
    SMOKE_ENV as JOBQUEUE_SMOKE_ENV,
    SMOKE_PROFILE_ENV as JOBQUEUE_PROFILE_ENV,
    SMOKE_SERVICE_ENV as JOBQUEUE_SERVICE_ENV,
    run_postgres_jobqueue_smoke,
)
from run_postgres_job_replay_smoke import (  # noqa: E402
    SMOKE_ENV as JOB_REPLAY_SMOKE_ENV,
    SMOKE_PROFILE_ENV as JOB_REPLAY_PROFILE_ENV,
    SMOKE_SERVICE_ENV as JOB_REPLAY_SERVICE_ENV,
    run_postgres_job_replay_smoke,
)
from run_postgres_operational_event_smoke import (  # noqa: E402
    SMOKE_ENV as EVENT_SMOKE_ENV,
    SMOKE_PROFILE_ENV as EVENT_PROFILE_ENV,
    SMOKE_SERVICE_ENV as EVENT_SERVICE_ENV,
    run_postgres_operational_event_smoke,
)
from run_postgres_service_log_smoke import (  # noqa: E402
    SMOKE_ENV as SERVICE_LOG_SMOKE_ENV,
    SMOKE_PROFILE_ENV as SERVICE_LOG_PROFILE_ENV,
    SMOKE_SERVICE_ENV as SERVICE_LOG_SERVICE_ENV,
    run_postgres_service_log_smoke,
)
from run_postgres_service_log_retention_smoke import (  # noqa: E402
    SMOKE_ENV as SERVICE_LOG_RETENTION_SMOKE_ENV,
    SMOKE_PROFILE_ENV as SERVICE_LOG_RETENTION_PROFILE_ENV,
    SMOKE_SERVICE_ENV as SERVICE_LOG_RETENTION_SERVICE_ENV,
    run_postgres_service_log_retention_smoke,
)
from run_postgres_service_log_retention_http_smoke import (  # noqa: E402
    SMOKE_ENV as SERVICE_LOG_RETENTION_HTTP_SMOKE_ENV,
    SMOKE_PROFILE_ENV as SERVICE_LOG_RETENTION_HTTP_PROFILE_ENV,
    SMOKE_SERVICE_ENV as SERVICE_LOG_RETENTION_HTTP_SERVICE_ENV,
    run_postgres_service_log_retention_http_smoke,
)
from run_postgres_operations_smoke_pack import (  # noqa: E402
    SMOKE_ENV as OPERATIONS_PACK_SMOKE_ENV,
    SMOKE_PROFILE_ENV as OPERATIONS_PACK_PROFILE_ENV,
    SMOKE_SERVICES_ENV as OPERATIONS_PACK_SERVICES_ENV,
    run_postgres_operations_smoke_pack,
)


SMOKE_ENV = "NEX_POSTGRES_TEST_SMOKE_SUITE"
SMOKE_PROFILE_ENV = "NEX_POSTGRES_TEST_SMOKE_SUITE_PROFILE"
SMOKE_SERVICES_ENV = "NEX_POSTGRES_TEST_SMOKE_SUITE_SERVICES"
SMOKE_PRIMARY_SERVICE_ENV = "NEX_POSTGRES_TEST_SMOKE_SUITE_PRIMARY_SERVICE"
DEFAULT_PROFILE = "test"
DEFAULT_PRIMARY_SERVICE_ID = "nex-cx"
DEFAULT_SERVICE_IDS = tuple(sorted(SERVICE_SPECS))
SCHEMA_VERSION = "postgres_test_smoke_suite.v1"
SUITE_STAGE_ORDER = (
    "readiness",
    "migrations",
    "jobqueue",
    "job_replay",
    "operational_events",
    "service_logs",
    "service_log_retention",
    "service_log_retention_http",
    "operations_pack",
    "cx_processing_jobqueue",
    "cx_processing_events",
    "ag_cross_service_observability",
)


def run_postgres_test_smoke_suite(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    service_ids = _selected_service_ids(env.get(SMOKE_SERVICES_ENV))
    primary_service_id = env.get(SMOKE_PRIMARY_SERVICE_ENV, DEFAULT_PRIMARY_SERVICE_ID)
    preflight_failure = _preflight_failure(
        profile=profile,
        service_ids=service_ids,
        primary_service_id=primary_service_id,
    )
    if preflight_failure is not None:
        return preflight_failure

    stages: dict[str, object] = {}
    readiness = _run_readiness_stage(
        service_ids=service_ids,
        profile=profile,
        env=env,
    )
    stages["readiness"] = readiness
    if readiness["status"] != "PASS":
        return _suite_evidence(
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
            stages=stages,
        )

    migrations = _run_migration_stage(
        service_ids=service_ids,
        profile=profile,
        env=env,
    )
    stages["migrations"] = migrations
    if migrations["status"] != "PASS":
        return _suite_evidence(
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
            stages=stages,
        )

    smoke_env = {
        **env,
        JOBQUEUE_SMOKE_ENV: "1",
        JOBQUEUE_SERVICE_ENV: primary_service_id,
        JOBQUEUE_PROFILE_ENV: profile,
        JOB_REPLAY_SMOKE_ENV: "1",
        JOB_REPLAY_SERVICE_ENV: primary_service_id,
        JOB_REPLAY_PROFILE_ENV: profile,
        EVENT_SMOKE_ENV: "1",
        EVENT_SERVICE_ENV: primary_service_id,
        EVENT_PROFILE_ENV: profile,
        SERVICE_LOG_SMOKE_ENV: "1",
        SERVICE_LOG_SERVICE_ENV: primary_service_id,
        SERVICE_LOG_PROFILE_ENV: profile,
        SERVICE_LOG_RETENTION_SMOKE_ENV: "1",
        SERVICE_LOG_RETENTION_SERVICE_ENV: primary_service_id,
        SERVICE_LOG_RETENTION_PROFILE_ENV: profile,
        SERVICE_LOG_RETENTION_HTTP_SMOKE_ENV: "1",
        SERVICE_LOG_RETENTION_HTTP_SERVICE_ENV: primary_service_id,
        SERVICE_LOG_RETENTION_HTTP_PROFILE_ENV: profile,
        OPERATIONS_PACK_SMOKE_ENV: "1",
        OPERATIONS_PACK_PROFILE_ENV: profile,
        OPERATIONS_PACK_SERVICES_ENV: ",".join(service_ids),
        CX_PROCESSING_JOBQUEUE_SMOKE_ENV: "1",
        CX_PROCESSING_JOBQUEUE_PROFILE_ENV: profile,
        CX_PROCESSING_EVENT_SMOKE_ENV: "1",
        CX_PROCESSING_EVENT_PROFILE_ENV: profile,
        AG_OBSERVABILITY_SMOKE_ENV: "1",
        AG_OBSERVABILITY_PROFILE_ENV: profile,
    }
    stages["jobqueue"] = _stage_from_child_smoke(
        run_postgres_jobqueue_smoke(environ=smoke_env)
    )
    stages["job_replay"] = _stage_from_child_smoke(
        run_postgres_job_replay_smoke(environ=smoke_env)
    )
    stages["operational_events"] = _stage_from_child_smoke(
        run_postgres_operational_event_smoke(environ=smoke_env)
    )
    stages["service_logs"] = _stage_from_child_smoke(
        run_postgres_service_log_smoke(environ=smoke_env)
    )
    stages["service_log_retention"] = _stage_from_child_smoke(
        run_postgres_service_log_retention_smoke(environ=smoke_env)
    )
    stages["service_log_retention_http"] = _stage_from_child_smoke(
        run_postgres_service_log_retention_http_smoke(environ=smoke_env)
    )
    stages["operations_pack"] = _stage_from_child_smoke(
        run_postgres_operations_smoke_pack(environ=smoke_env)
    )
    stages["cx_processing_jobqueue"] = _stage_from_child_smoke(
        run_cx_processing_postgres_jobqueue_smoke(environ=smoke_env)
    )
    stages["cx_processing_events"] = _stage_from_child_smoke(
        run_cx_processing_postgres_event_smoke(environ=smoke_env)
    )
    stages["ag_cross_service_observability"] = _stage_from_child_smoke(
        run_ag_cross_service_observability_smoke(environ=smoke_env)
    )
    return _suite_evidence(
        profile=profile,
        service_ids=service_ids,
        primary_service_id=primary_service_id,
        stages=stages,
    )


def _selected_service_ids(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_SERVICE_IDS
    return tuple(
        service_id.strip()
        for service_id in raw_value.split(",")
        if service_id.strip()
    )


def _preflight_failure(
    *,
    profile: str,
    service_ids: tuple[str, ...],
    primary_service_id: str,
) -> dict[str, object] | None:
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for PostgreSQL write smoke execution.",
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
        )
    unknown_services = [
        service_id
        for service_id in (*service_ids, primary_service_id)
        if service_id not in SERVICE_SPECS
    ]
    if unknown_services:
        return _failure(
            "service_invalid",
            f"unknown service ids: {', '.join(sorted(set(unknown_services)))}",
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
        )
    if not service_ids:
        return _failure(
            "service_selection_empty",
            f"{SMOKE_SERVICES_ENV} selected no services.",
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
        )
    if primary_service_id != DEFAULT_PRIMARY_SERVICE_ID:
        return _failure(
            "primary_service_not_supported",
            f"{SMOKE_PRIMARY_SERVICE_ENV} must be {DEFAULT_PRIMARY_SERVICE_ID}.",
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
        )
    if primary_service_id not in service_ids:
        return _failure(
            "primary_service_not_selected",
            f"{SMOKE_PRIMARY_SERVICE_ENV} must be included in {SMOKE_SERVICES_ENV}.",
            profile=profile,
            service_ids=service_ids,
            primary_service_id=primary_service_id,
        )
    return None


def _run_readiness_stage(
    *,
    service_ids: tuple[str, ...],
    profile: str,
    env: dict[str, str],
) -> dict[str, object]:
    services: list[dict[str, object]] = []
    for service_id in service_ids:
        try:
            database_env = service_database_env(service_id, profile=profile)
            database_url = service_database_url(service_id, profile=profile, environ=env)
        except MigrationError as exc:
            services.append(
                {
                    "service_id": service_id,
                    "status": "FAIL",
                    "failure_code": "configuration_invalid",
                    "detail": str(exc),
                }
            )
            continue
        check = check_database_readiness(database_env, environ=env)
        service: dict[str, object] = {
            "service_id": service_id,
            "status": "PASS" if check["ok"] else "FAIL",
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "readiness": _readiness_summary(check),
        }
        if not check["ok"]:
            service["failure_code"] = "readiness_failed"
        services.append(service)
    return _stage_evidence("readiness", services)


def _run_migration_stage(
    *,
    service_ids: tuple[str, ...],
    profile: str,
    env: dict[str, str],
) -> dict[str, object]:
    services: list[dict[str, object]] = []
    for service_id in service_ids:
        try:
            database_env = service_database_env(service_id, profile=profile)
            database_url = service_database_url(service_id, profile=profile, environ=env)
            result = run_service_migrations(
                service_id,
                database_url=database_url,
                profile=profile,
            )
        except (MigrationError, ValueError) as exc:
            services.append(
                {
                    "service_id": service_id,
                    "status": "FAIL",
                    "failure_code": "migration_failed",
                    "detail": str(exc),
                }
            )
            continue
        services.append(
            {
                "service_id": service_id,
                "status": "PASS",
                "profile": profile,
                "database_env": database_env,
                "redacted_database_url": redact_database_url(database_url),
                "planned": list(result.planned),
                "applied": list(result.applied),
                "skipped": list(result.skipped),
            }
        )
    return _stage_evidence("migrations", services)


def _stage_from_child_smoke(evidence: dict[str, object]) -> dict[str, object]:
    status = str(evidence["status"])
    stage = {
        "status": status,
        "smoke_schema_version": evidence["smoke_schema_version"],
    }
    for key in (
        "service_id",
        "service_count",
        "profile",
        "database_env",
        "failure_code",
        "checks",
    ):
        if key in evidence:
            stage[key] = evidence[key]
    return stage


def _stage_evidence(stage_name: str, services: list[dict[str, object]]) -> dict[str, object]:
    failed_services = [
        str(service["service_id"])
        for service in services
        if service["status"] != "PASS"
    ]
    stage: dict[str, object] = {
        "status": "PASS" if not failed_services else "FAIL",
        "service_count": len(services),
        "services": services,
    }
    if failed_services:
        stage["failure_code"] = f"{stage_name}_failed"
        stage["failed_services"] = failed_services
    return stage


def _suite_evidence(
    *,
    profile: str,
    service_ids: tuple[str, ...],
    primary_service_id: str,
    stages: dict[str, object],
) -> dict[str, object]:
    failed_stage = _first_failed_stage(stages)
    evidence: dict[str, object] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS" if failed_stage is None else "FAIL",
        "profile": profile,
        "service_ids": list(service_ids),
        "service_count": len(service_ids),
        "primary_service_id": primary_service_id,
        "stage_order": list(SUITE_STAGE_ORDER),
        "stages": stages,
        "checks": {
            stage_name: (
                stage_name in stages
                and isinstance(stages[stage_name], dict)
                and stages[stage_name].get("status") == "PASS"
            )
            for stage_name in SUITE_STAGE_ORDER
        },
    }
    if failed_stage is not None:
        evidence["failure_code"] = "stage_failed"
        evidence["failed_stage"] = failed_stage
    return evidence


def _first_failed_stage(stages: dict[str, object]) -> str | None:
    for stage_name in SUITE_STAGE_ORDER:
        stage = stages.get(stage_name)
        if isinstance(stage, dict) and stage.get("status") != "PASS":
            return stage_name
    return None


def _readiness_summary(readiness: dict[str, Any]) -> dict[str, object]:
    if not readiness.get("ok"):
        return {
            "ok": False,
            "database_env": readiness.get("database_env"),
            "error_code": readiness.get("error_code"),
            "latency_ms": readiness.get("latency_ms"),
        }
    return {
        "ok": True,
        "database_env": readiness.get("database_env"),
        "database_name": readiness.get("database_name"),
        "database_user": readiness.get("database_user"),
        "latency_ms": readiness.get("latency_ms"),
    }


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    service_ids: tuple[str, ...],
    primary_service_id: str,
) -> dict[str, object]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "profile": profile,
        "service_ids": list(service_ids),
        "service_count": len(service_ids),
        "primary_service_id": primary_service_id,
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"postgres_test_smoke_suite=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "postgres_test_smoke_suite=pass "
            f"services={evidence['service_count']} profile={evidence['profile']} "
            f"primary={evidence['primary_service_id']} stages={len(SUITE_STAGE_ORDER)}"
        )
    return (
        "postgres_test_smoke_suite=fail "
        f"services={evidence.get('service_count')} reason={evidence.get('failure_code')} "
        f"stage={evidence.get('failed_stage')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the optional PostgreSQL test-profile smoke suite."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_test_smoke_suite()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
