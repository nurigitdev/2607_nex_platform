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
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))

from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    check_database_readiness,
    load_env_file,
    redact_database_url,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    service_database_env,
    service_database_url,
)
from run_postgres_jobqueue_smoke import (  # noqa: E402
    SMOKE_ENV as JOBQUEUE_SMOKE_ENV,
    SMOKE_PROFILE_ENV as JOBQUEUE_PROFILE_ENV,
    SMOKE_SERVICE_ENV as JOBQUEUE_SERVICE_ENV,
    run_postgres_jobqueue_smoke,
)
from run_postgres_operational_event_smoke import (  # noqa: E402
    SMOKE_ENV as EVENT_SMOKE_ENV,
    SMOKE_PROFILE_ENV as EVENT_PROFILE_ENV,
    SMOKE_SERVICE_ENV as EVENT_SERVICE_ENV,
    run_postgres_operational_event_smoke,
)


SMOKE_ENV = "NEX_DB_OPERATIONS_SMOKE"
SMOKE_PROFILE_ENV = "NEX_DB_OPERATIONS_SMOKE_PROFILE"
SMOKE_SERVICES_ENV = "NEX_DB_OPERATIONS_SMOKE_SERVICES"
DEFAULT_PROFILE = "test"
DEFAULT_SERVICE_IDS = tuple(sorted(SERVICE_SPECS))


def run_postgres_operations_smoke_pack(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "postgres_operations_smoke_pack.v1",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    service_ids = _selected_service_ids(env.get(SMOKE_SERVICES_ENV))
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for cross-service write smoke execution.",
            profile=profile,
            service_ids=service_ids,
        )
    unknown_services = [service_id for service_id in service_ids if service_id not in SERVICE_SPECS]
    if unknown_services:
        return _failure(
            "service_invalid",
            f"unknown service ids: {', '.join(unknown_services)}",
            profile=profile,
            service_ids=service_ids,
        )
    if not service_ids:
        return _failure(
            "service_selection_empty",
            f"{SMOKE_SERVICES_ENV} selected no services.",
            profile=profile,
            service_ids=service_ids,
        )

    services = [
        _run_service_operations_smoke(
            service_id=service_id,
            profile=profile,
            env=env,
        )
        for service_id in service_ids
    ]
    failed_services = [
        service["service_id"]
        for service in services
        if service["status"] != "PASS"
    ]
    status = "PASS" if not failed_services else "FAIL"
    evidence: dict[str, object] = {
        "smoke_schema_version": "postgres_operations_smoke_pack.v1",
        "status": status,
        "profile": profile,
        "service_count": len(services),
        "services": services,
        "checks": {
            "all_readiness": all(_check_status(service, "readiness") for service in services),
            "all_jobqueue": all(_check_status(service, "jobqueue") for service in services),
            "all_operational_events": all(
                _check_status(service, "operational_events") for service in services
            ),
        },
    }
    if failed_services:
        evidence["failure_code"] = "service_smoke_failed"
        evidence["failed_services"] = failed_services
    return evidence


def _run_service_operations_smoke(
    *,
    service_id: str,
    profile: str,
    env: dict[str, str],
) -> dict[str, object]:
    try:
        database_env = service_database_env(service_id, profile=profile)
        database_url = service_database_url(service_id, profile=profile, environ=env)
    except MigrationError as exc:
        return {
            "service_id": service_id,
            "status": "FAIL",
            "failure_code": "configuration_invalid",
            "detail": str(exc),
            "checks": {
                "readiness": "FAIL",
                "jobqueue": "SKIPPED",
                "operational_events": "SKIPPED",
            },
        }

    readiness = check_database_readiness(database_env, environ=env)
    if not readiness["ok"]:
        return {
            "service_id": service_id,
            "status": "FAIL",
            "failure_code": "readiness_failed",
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "readiness": readiness,
            "checks": {
                "readiness": "FAIL",
                "jobqueue": "SKIPPED",
                "operational_events": "SKIPPED",
            },
        }

    jobqueue = run_postgres_jobqueue_smoke(
        environ={
            **env,
            JOBQUEUE_SMOKE_ENV: "1",
            JOBQUEUE_SERVICE_ENV: service_id,
            JOBQUEUE_PROFILE_ENV: profile,
        }
    )
    operational_events = run_postgres_operational_event_smoke(
        environ={
            **env,
            EVENT_SMOKE_ENV: "1",
            EVENT_SERVICE_ENV: service_id,
            EVENT_PROFILE_ENV: profile,
        }
    )
    checks = {
        "readiness": "PASS",
        "jobqueue": str(jobqueue["status"]),
        "operational_events": str(operational_events["status"]),
    }
    service_status = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
    service: dict[str, object] = {
        "service_id": service_id,
        "status": service_status,
        "database_env": database_env,
        "redacted_database_url": redact_database_url(database_url),
        "readiness": _readiness_summary(readiness),
        "jobqueue": _subsmoke_summary(jobqueue),
        "operational_events": _subsmoke_summary(operational_events),
        "checks": checks,
    }
    if service_status != "PASS":
        service["failure_code"] = "subsmoke_failed"
    return service


def _selected_service_ids(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None or not raw_value.strip():
        return DEFAULT_SERVICE_IDS
    return tuple(
        service_id.strip()
        for service_id in raw_value.split(",")
        if service_id.strip()
    )


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


def _subsmoke_summary(evidence: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {
        "status": evidence["status"],
        "smoke_schema_version": evidence["smoke_schema_version"],
    }
    for key in ("service_id", "profile", "database_env", "failure_code", "checks"):
        if key in evidence:
            summary[key] = evidence[key]
    return summary


def _check_status(service: dict[str, object], check_name: str) -> bool:
    checks = service.get("checks", {})
    if not isinstance(checks, dict):
        return False
    return checks.get(check_name) == "PASS"


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    service_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "smoke_schema_version": "postgres_operations_smoke_pack.v1",
        "status": "FAIL",
        "profile": profile,
        "service_count": len(service_ids),
        "service_ids": list(service_ids),
        "failure_code": failure_code,
        "detail": detail,
    }


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"postgres_operations_smoke_pack=skipped reason={SMOKE_ENV}"
    if evidence["status"] == "PASS":
        return (
            "postgres_operations_smoke_pack=pass "
            f"services={evidence['service_count']} profile={evidence['profile']}"
        )
    return (
        "postgres_operations_smoke_pack=fail "
        f"services={evidence.get('service_count')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional cross-service PostgreSQL operations write smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_postgres_operations_smoke_pack()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
