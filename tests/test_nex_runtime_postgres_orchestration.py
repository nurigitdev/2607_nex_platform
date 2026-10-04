from __future__ import annotations

from dataclasses import replace

import pytest
import run_platform_postgres_restart_evidence as smoke

from nex_runtime.postgres_orchestration import (
    POOL_WORKLOADS,
    POSTGRES_ORCHESTRATION_PHASES,
    POSTGRES_SERVICE_ORDER,
    S133_POSTGRES_ORCHESTRATION_PLAN,
    PlatformPostgresRestartEvidence,
    PostgresOrchestrationEvidenceError,
    PostgresPhaseEvidence,
    build_platform_postgres_restart_evidence,
    build_postgres_phase_evidence,
    validate_platform_postgres_restart_evidence,
    validate_postgres_orchestration_plan,
)


def passed_record(service_id: str = "nex-oa", phase: str = "MIGRATION"):
    return build_postgres_phase_evidence(
        service_id=service_id,
        phase=phase,
        status="PASSED",
        evidence_codes=("migration_head_current",),
        duration_ms=12,
    )


def test_canonical_plan_is_strict_and_projects_without_secrets() -> None:
    projection = S133_POSTGRES_ORCHESTRATION_PLAN.to_public_projection()

    assert projection["service_order"] == POSTGRES_SERVICE_ORDER
    assert projection["phase_order"] == POSTGRES_ORCHESTRATION_PHASES
    assert projection["pool_workloads"] == POOL_WORKLOADS
    assert projection["production_database_allowed"] is False
    assert "url" not in str(projection).lower()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "v2", "schema_version"),
        ("requirement", "S134", "requirement"),
        ("profile", "production", "profile"),
        ("service_order", tuple(reversed(POSTGRES_SERVICE_ORDER)), "service_order"),
        ("phase_order", tuple(reversed(POSTGRES_ORCHESTRATION_PHASES)), "phase_order"),
        ("pool_workloads", ("api",), "pool_workloads"),
        ("restart_count", 2, "restart_count"),
        ("production_database_allowed", True, "production_database"),
        ("remote_provider_required", True, "remote_provider"),
    ],
)
def test_plan_rejects_boundary_drift(field, value, message) -> None:
    with pytest.raises(PostgresOrchestrationEvidenceError, match=message):
        validate_postgres_orchestration_plan(
            replace(S133_POSTGRES_ORCHESTRATION_PLAN, **{field: value})
        )


def test_phase_evidence_and_run_projection_are_privacy_safe() -> None:
    records = tuple(passed_record(service_id) for service_id in POSTGRES_SERVICE_ORDER)
    evidence = build_platform_postgres_restart_evidence(
        run_id="s133-smoke-001",
        state="PASSED",
        records=records,
    )

    projection = evidence.to_public_projection()

    assert projection["schema_version"] == "platform_postgres_restart_evidence.v1"
    assert projection["service_count"] == 5
    assert projection["record_count"] == 5
    assert projection["status_counts"]["PASSED"] == 5
    assert projection["status_counts"]["FAILED"] == 0
    assert "password" not in str(projection).lower()


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"service_id": "unknown"}, "service_id"),
        ({"phase": "CONNECT"}, "phase"),
        ({"status": "SKIPPED"}, "status"),
        ({"restart_iteration": 2}, "restart_iteration"),
        ({"duration_ms": -1}, "duration_ms"),
        ({"evidence_codes": ("same", "same")}, "evidence_codes_duplicate"),
        ({"evidence_codes": ("postgresql://user:secret@host/db",)}, "evidence_code"),
        ({"status": "PASSED", "evidence_codes": ()}, "passed_evidence"),
        ({"status": "FAILED", "failure_code": None}, "failure_code_required"),
        ({"status": "FAILED", "failure_code": "bad secret value"}, "failure_code_required"),
        ({"status": "RUNNING", "failure_code": "unexpected"}, "failure_code_forbidden"),
    ],
)
def test_phase_evidence_rejects_invalid_or_sensitive_shapes(replacement, message) -> None:
    values = {
        "service_id": "nex-cx",
        "phase": "STARTUP",
        "status": "RUNNING",
        "restart_iteration": 0,
        "evidence_codes": (),
        "duration_ms": 0,
        "failure_code": None,
    }
    values.update(replacement)

    with pytest.raises(PostgresOrchestrationEvidenceError, match=message):
        build_postgres_phase_evidence(**values)


def test_failed_record_and_failed_run_require_normalized_failure() -> None:
    record = build_postgres_phase_evidence(
        service_id="nex-ag",
        phase="RESTORATION",
        status="FAILED",
        restart_iteration=1,
        failure_code="durable_state_missing",
    )
    evidence = build_platform_postgres_restart_evidence(
        run_id="s133-failed-001",
        state="FAILED",
        records=(record,),
    )

    assert evidence.to_public_projection()["status_counts"]["FAILED"] == 1


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        (
            PlatformPostgresRestartEvidence("unsafe run id", "RUNNING", (passed_record(),)),
            "run_id",
        ),
        (
            PlatformPostgresRestartEvidence("safe", "DONE", (passed_record(),)),
            "run_state",
        ),
        (PlatformPostgresRestartEvidence("safe", "NEW", ()), "records"),
        (
            PlatformPostgresRestartEvidence(
                "safe", "RUNNING", (passed_record(), passed_record())
            ),
            "duplicate",
        ),
        (
            PlatformPostgresRestartEvidence("safe", "FAILED", (passed_record(),)),
            "failed_state",
        ),
        (
            PlatformPostgresRestartEvidence(
                "safe",
                "PASSED",
                (
                    PostgresPhaseEvidence(
                        "nex-oa", "STARTUP", "RUNNING", 0, (), 0
                    ),
                ),
            ),
            "passed_state",
        ),
    ],
)
def test_run_evidence_rejects_invalid_state_combinations(evidence, message) -> None:
    with pytest.raises(PostgresOrchestrationEvidenceError, match=message):
        validate_platform_postgres_restart_evidence(evidence)


def test_smoke_report_summary_and_main(monkeypatch, capsys) -> None:
    report = smoke.build_report()

    assert report["status"] == "PASS"
    assert smoke.summary_line(report) == (
        "platform_postgres_restart_evidence=pass services=5 records=5 next=1324"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_postgres_restart_evidence=fail"
    )
    assert smoke.main(["--summary"]) == 0
    assert "services=5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(smoke, "build_report", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1
