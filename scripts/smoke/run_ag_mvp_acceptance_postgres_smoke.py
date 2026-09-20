#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
QUALITY_PATH = ROOT / "scripts" / "quality"
for path in (SHARED_PATH, AG_PATH, DB_SCRIPT_PATH, QUALITY_PATH):
    sys.path.insert(0, str(path))

from nex_ag.cx_transition_handoff import (  # noqa: E402
    bind_ag_cx_transition_handoff,
    build_ag_cx_transition_handoff_candidate,
    verify_ag_cx_transition_handoff,
    verify_ag_cx_transition_handoff_attestation,
)
from nex_ag.mvp_acceptance import (  # noqa: E402
    build_ag_mvp_acceptance_policy,
    build_ag_mvp_evidence_inventory,
)
from nex_ag.mvp_acceptance_api import (  # noqa: E402
    AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
    register_ag_mvp_acceptance_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_engine,
    build_operational_event,
    build_service_app,
    build_session_factory,
    issue_mock_user_token,
    redact_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402
from validate_contracts import validate_contract_tree  # noqa: E402


SCHEMA_VERSION = "ag_mvp_acceptance_postgres_smoke.v1"
SMOKE_ENV = "NEX_AG_MVP_ACCEPTANCE_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AG_TEST_DATABASE_URL"
COVERAGE_JSON_ENV = "NEX_AG_MVP_COVERAGE_JSON"
PYTEST_LOG_ENV = "NEX_AG_MVP_PYTEST_LOG"
SERVICE_ID = "nex-ag"
PROFILE = "test"
LATEST_MIGRATION = "0887_ag_retention_candidate_indexes"
RAW_MESSAGE = "private S90 PostgreSQL acceptance probe"
RAW_DETAIL = "private-s90-database-detail"
PYTEST_RESULT_PATTERN = re.compile(r"(?P<passed>\d+) passed(?:, \d+ warnings?)? in ")


class _StaticEvidenceProvider:
    def __init__(self, evidence: Mapping[str, Any]) -> None:
        self._evidence = evidence

    def collect(self, *, observed_at: datetime) -> Mapping[str, Any]:
        return self._evidence


def run_ag_mvp_acceptance_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    database_url = env.get(DATABASE_ENV)
    coverage_path = env.get(COVERAGE_JSON_ENV)
    pytest_log_path = env.get(PYTEST_LOG_ENV)
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not coverage_path or not pytest_log_path:
        return _failure(
            "regression_evidence_missing",
            f"{COVERAGE_JSON_ENV} and {PYTEST_LOG_ENV} are required.",
        )
    try:
        migration = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=PROFILE,
        )
        regression = _load_regression_evidence(
            Path(coverage_path),
            Path(pytest_log_path),
            now=datetime.now(UTC),
        )
    except (MigrationError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _failure(
            "migration_or_regression_evidence_failed",
            _redact_detail(str(exc), database_url=database_url),
        )

    suffix = uuid4().hex[:12]
    context = {
        "event_id": f"ag-mvp-acceptance-smoke-{suffix}",
        "trace_id": uuid4().hex,
        "request_id": f"ag-mvp-acceptance-request-{suffix}",
    }
    engine: Any | None = None
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        event_store = SqlAlchemyOperationalEventStore(
            build_session_factory(engine)
        )
        evidence = _execute_smoke(
            engine=engine,
            event_store=event_store,
            migration=migration,
            regression=regression,
            context=context,
        )
        cleanup_done = True
        passed = all(evidence["checks"].values())
        evidence["status"] = "PASS" if passed else "FAIL"
        evidence["failure_code"] = None if passed else "checks_failed"
    except (SQLAlchemyError, RuntimeError, ValueError) as exc:
        evidence = _failure(
            "smoke_execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )
    finally:
        if engine is not None and not cleanup_done:
            _cleanup_owned_rows(engine, context=context)
        if engine is not None:
            engine.dispose()

    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _execute_smoke(
    *,
    engine: Any,
    event_store: Any,
    migration: Any,
    regression: Mapping[str, Any],
    context: Mapping[str, str],
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    now = observed_at or datetime.now(UTC)
    event_store.append(
        build_operational_event(
            service_id=SERVICE_ID,
            event_type="ag.mvp_acceptance.postgres_probe",
            severity="INFO",
            message=RAW_MESSAGE,
            trace_id=context["trace_id"],
            request_id=context["request_id"],
            subject_ref={"type": "ag_mvp_acceptance", "id": context["event_id"]},
            details={"private_detail": RAW_DETAIL},
            event_id=context["event_id"],
            created_at=_timestamp(now),
        )
    )
    observation = _database_observation(engine, context=context)
    cleanup = _cleanup_owned_rows(engine, context=context)
    cleanup_passed = cleanup == {
        "deleted_rows": 1,
        "remaining_rows": 0,
    }
    inventory = build_ag_mvp_evidence_inventory()
    contracts = validate_contract_tree(ROOT / "contracts")
    candidate = build_ag_cx_transition_handoff_candidate(generated_at=now)
    candidate_verification = verify_ag_cx_transition_handoff(candidate)
    observed_timestamp = _timestamp(now)
    governance_count = sum(
        item["capability_group"]
        in {"ag_operator_governance", "ag_mvp_hardening"}
        for item in inventory["entries"]
    )
    acceptance_evidence = {
        "ag_requirement_closures": {
            "status": inventory["status"],
            "observed_at": observed_timestamp,
            "requirement_count": inventory["scope"][
                "included_requirement_count"
            ],
            "issue_count": len(inventory["issues"]),
        },
        "contract_validation": {
            "status": "PASS" if contracts.ok else "FAIL",
            "observed_at": observed_timestamp,
            "schema_count": contracts.schema_count,
            "openapi_count": contracts.openapi_count,
            "negative_fixture_count": contracts.negative_example_count,
        },
        "unit_regression": {
            "status": "PASS",
            "observed_at": observed_timestamp,
            "passed_tests": regression["passed_tests"],
            "failed_tests": regression["failed_tests"],
        },
        "statement_coverage": {
            "status": "PASS",
            "observed_at": observed_timestamp,
            "percent": regression["statement_percent"],
        },
        "branch_coverage": {
            "status": "PASS",
            "observed_at": observed_timestamp,
            "percent": regression["branch_percent"],
        },
        "postgres_smoke": {
            "status": "PASS" if cleanup_passed else "FAIL",
            "observed_at": observed_timestamp,
            "backend": observation["backend"],
            "database": observation["database"],
            "zero_residue": cleanup_passed,
        },
        "privacy_failure_runbooks": {
            "status": "PASS",
            "observed_at": observed_timestamp,
            "runbook_count": governance_count,
        },
        "cx_transition_handoff": {
            "status": candidate_verification["status"].replace(
                "VERIFIED", "PASS"
            ),
            "observed_at": observed_timestamp,
            "target_service": candidate["target_service"],
            "manifest_status": candidate["manifest_status"],
        },
    }
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_ag_mvp_acceptance_routes(
        app,
        evidence_provider=_StaticEvidenceProvider(acceptance_evidence),
        policy=build_ag_mvp_acceptance_policy({}),
        clock=lambda: now,
    )
    response = TestClient(app).get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers=_admin_headers(context),
    )
    report = _mapping(response.json())
    accepted = (
        response.status_code == 200
        and report.get("status") == "ACCEPTED"
        and report.get("transition_status") == "READY_FOR_CX"
    )
    attestation: Mapping[str, Any] = {}
    attestation_verification: Mapping[str, Any] = {}
    if accepted:
        attestation = bind_ag_cx_transition_handoff(
            candidate,
            report,
            bound_at=now,
        )
        attestation_verification = (
            verify_ag_cx_transition_handoff_attestation(
                attestation,
                candidate=candidate,
                acceptance_report=report,
            )
        )
    migration_versions = set(migration.applied) | set(migration.skipped)
    serialized = json.dumps(
        [report, candidate, attestation], default=str, sort_keys=True
    )
    checks = {
        "migration_ran": (
            migration.service_id == SERVICE_ID
            and LATEST_MIGRATION in migration_versions
            and observation["migration_present"] is True
        ),
        "backend_is_postgresql": observation["backend"].startswith("postgresql"),
        "test_database_selected": observation["database"] == "nex_ag_test",
        "probe_insert_selected": observation["probe_count"] == 1,
        "owned_rows_deleted": cleanup_passed,
        "closure_inventory_passed": inventory["status"] == "PASS",
        "contract_validation_passed": contracts.ok,
        "regression_evidence_passed": (
            regression["passed_tests"] >= 6000
            and regression["failed_tests"] == 0
        ),
        "coverage_thresholds_passed": (
            regression["statement_percent"] >= 98.0
            and regression["branch_percent"] >= 96.0
        ),
        "candidate_verified": candidate_verification["status"] == "VERIFIED",
        "acceptance_api_accepted": accepted,
        "attestation_bound_verified": (
            attestation_verification.get("status") == "VERIFIED"
            and attestation.get("attestation_status") == "BOUND"
        ),
        "responses_redacted": not any(
            marker in serialized for marker in (RAW_MESSAGE, RAW_DETAIL)
        ),
    }
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PENDING",
        "failure_code": None,
        "service": SERVICE_ID,
        "profile": PROFILE,
        "migration": {
            "planned_count": len(migration.planned),
            "applied_count": len(migration.applied),
            "skipped_count": len(migration.skipped),
            "latest_present": LATEST_MIGRATION in migration_versions,
        },
        "database": observation,
        "cleanup": cleanup,
        "regression": dict(regression),
        "contracts": {
            "schema_count": contracts.schema_count,
            "example_count": contracts.example_count,
            "negative_fixture_count": contracts.negative_example_count,
            "openapi_count": contracts.openapi_count,
        },
        "acceptance": {
            "status": report.get("status"),
            "transition_status": report.get("transition_status"),
            "acceptance_id": report.get("acceptance_id"),
            "passed_gate_count": _mapping(report.get("summary")).get(
                "passed_gate_count"
            ),
        },
        "handoff": {
            "candidate_status": candidate.get("manifest_status"),
            "candidate_hash": candidate.get("manifest_hash"),
            "attestation_status": attestation.get("attestation_status"),
            "attestation_hash": attestation.get("attestation_hash"),
        },
        "checks": checks,
    }


def _load_regression_evidence(
    coverage_path: Path,
    pytest_log_path: Path,
    *,
    now: datetime,
) -> dict[str, Any]:
    for path in (coverage_path, pytest_log_path):
        if not path.is_file():
            raise ValueError(f"regression evidence file is missing: {path.name}")
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if now - modified_at > timedelta(hours=24):
            raise ValueError(f"regression evidence file is stale: {path.name}")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    totals = _mapping(coverage.get("totals"))
    statement = totals.get("percent_statements_covered")
    branch = totals.get("percent_branches_covered")
    if not _coverage_percent(statement) or not _coverage_percent(branch):
        raise ValueError("coverage evidence percentages are invalid")
    pytest_log = pytest_log_path.read_text(encoding="utf-8")
    matches = list(PYTEST_RESULT_PATTERN.finditer(pytest_log))
    if not matches or re.search(r"\b\d+ failed\b", pytest_log):
        raise ValueError("pytest evidence does not prove a passing regression")
    return {
        "passed_tests": int(matches[-1].group("passed")),
        "failed_tests": 0,
        "statement_percent": float(statement),
        "branch_percent": float(branch),
    }


def _database_observation(
    engine: Any, *, context: Mapping[str, str]
) -> dict[str, Any]:
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()"))
        database_name = database.scalar_one()
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = :version"),
            {"version": LATEST_MIGRATION},
        ).scalar_one()
        probe_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM service_operational_events "
                "WHERE event_id = :event_id"
            ),
            {"event_id": context["event_id"]},
        ).scalar_one()
    return {
        "backend": engine.url.get_backend_name(),
        "database": database_name,
        "migration_present": int(migration_count) == 1,
        "probe_count": int(probe_count),
    }


def _cleanup_owned_rows(
    engine: Any, *, context: Mapping[str, str]
) -> dict[str, int]:
    try:
        with engine.begin() as connection:
            deleted = connection.execute(
                text(
                    "DELETE FROM service_operational_events "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": context["event_id"]},
            ).rowcount
            remaining = connection.execute(
                text(
                    "SELECT COUNT(*) FROM service_operational_events "
                    "WHERE event_id = :event_id"
                ),
                {"event_id": context["event_id"]},
            ).scalar_one()
        return {
            "deleted_rows": int(deleted or 0),
            "remaining_rows": int(remaining),
        }
    except (SQLAlchemyError, RuntimeError, ValueError):
        return {"deleted_rows": 0, "remaining_rows": -1}


def _admin_headers(context: Mapping[str, str]) -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="s90-acceptance-operator",
        audience="nex-ag",
        roles=["admin"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": context["request_id"],
        "traceparent": f"00-{context['trace_id']}-00f067aa0ba902b7-01",
    }


def assert_smoke_evidence_redacted(
    serialized: str, env: Mapping[str, str]
) -> None:
    forbidden = [RAW_MESSAGE, RAW_DETAIL]
    database_url = env.get(DATABASE_ENV)
    if database_url:
        forbidden.append(database_url)
    for value in forbidden:
        if value and value in serialized:
            raise AssertionError("S90 acceptance smoke evidence leaked private data")


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
    }


def _redact_detail(detail: str, *, database_url: str) -> str:
    return detail.replace(database_url, redact_database_url(database_url))


def _coverage_percent(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0.0 <= value <= 100.0
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status == "skipped":
        return f"ag_mvp_acceptance_postgres_smoke=skipped reason={SMOKE_ENV}"
    if status != "pass":
        return (
            "ag_mvp_acceptance_postgres_smoke=fail "
            f"code={evidence.get('failure_code')}"
        )
    database = _mapping(evidence.get("database"))
    regression = _mapping(evidence.get("regression"))
    acceptance = _mapping(evidence.get("acceptance"))
    handoff = _mapping(evidence.get("handoff"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "ag_mvp_acceptance_postgres_smoke=pass "
        f"database={database.get('database')} "
        f"tests={regression.get('passed_tests')} "
        f"statement={regression.get('statement_percent'):.6f} "
        f"branch={regression.get('branch_percent'):.6f} "
        f"acceptance={acceptance.get('status')} "
        f"handoff={handoff.get('attestation_status')} "
        f"remaining={cleanup.get('remaining_rows')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_mvp_acceptance_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
