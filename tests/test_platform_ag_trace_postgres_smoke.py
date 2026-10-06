from __future__ import annotations

from types import SimpleNamespace

import pytest

import run_platform_ag_trace_postgres_smoke as smoke


def _migration_result():
    return SimpleNamespace(
        services=tuple(
            SimpleNamespace(migration_count=3, select_one_ready=True) for _ in range(5)
        )
    )


def _targets():
    return tuple(
        SimpleNamespace(
            target=SimpleNamespace(
                service_id=service_id,
                expected_database_name=f"{service_id}_test",
                expected_role_name=f"{service_id}_user",
            ),
            database_url=f"postgresql+psycopg://user:secret@localhost/{service_id}",
        )
        for service_id in smoke.SERVICE_IDS
    )


def _journey(*_targets):
    return {
        "status_code": 200,
        "projection_schema_version": "ag_cross_service_trace_e2e.v1",
        "source_statuses": {
            "nex-oa": "READY",
            "nex-ae-api": "READY",
            "nex-cx": "READY",
            "nex-mo": "READY",
            "nex-ag": "READY",
        },
        "stage_count": 9,
        "stage_families": [
            "AUTH",
            "UPLOAD",
            "INGESTION",
            "RETRIEVAL",
            "GENERATION",
            "ARTIFACT",
            "ACCESS",
            "OPERATIONS",
        ],
        "ag_audit_after_restart": 1,
        "database_identities": {service_id: True for service_id in smoke.SERVICE_IDS},
        "direct_cross_database_reads": 0,
        "private_payload_included": False,
        "cleanup_residue": {service_id: 0 for service_id in smoke.SERVICE_IDS},
    }


def test_protected_postgres_smoke_is_skipped_by_default() -> None:
    result = smoke.run_platform_ag_trace_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert result["actual_postgresql"] is False
    assert smoke.SMOKE_ENV in result["skip_reason"]


def test_protected_postgres_smoke_passes_with_injected_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "resolve_postgres_test_targets", lambda *_a, **_k: _targets()
    )

    result = smoke.run_platform_ag_trace_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "test"},
        migration_runner=lambda _env: _migration_result(),
        journey_runner=lambda targets: _journey(*targets),
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 9,
        "passed_check_count": 9,
        "service_count": 5,
        "migration_count": 15,
        "stage_count": 9,
        "stage_family_count": 8,
        "cleanup_residue_count": 0,
    }
    assert result["next_slice"] == "1381"
    assert result["source_statuses"]["nex-cx"] == "READY"
    assert len(result["stage_families"]) == 8


def test_postgres_journey_step_error_is_bounded() -> None:
    class Diagnostic:
        constraint_name = "ck_safe_constraint"

    class DriverError:
        diag = Diagnostic()

    class SeedFailure(Exception):
        orig = DriverError()

    with pytest.raises(smoke.TracePostgresSmokeStepError) as exc_info:
        smoke._run_step(
            "seed_ae",
            lambda: (_ for _ in ()).throw(SeedFailure("private SQL value")),
        )

    assert exc_info.value.failure_code == (
        "postgres_journey.seed_ae.SeedFailure.ck_safe_constraint"
    )
    assert "private SQL value" not in str(exc_info.value)
    assert smoke.TracePostgresSmokeStepError(
        "seed_cx", RuntimeError("private detail")
    ).failure_code == "postgres_journey.seed_cx.RuntimeError"


def test_postgres_journey_step_error_fails_top_level_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "resolve_postgres_test_targets", lambda *_a, **_k: _targets()
    )

    result = smoke.run_platform_ag_trace_postgres_smoke(
        {smoke.SMOKE_ENV: "1"},
        migration_runner=lambda _env: _migration_result(),
        journey_runner=lambda _targets: (_ for _ in ()).throw(
            smoke.TracePostgresSmokeStepError("seed_cx", RuntimeError("secret"))
        ),
    )

    assert result["failure_code"] == "postgres_journey.seed_cx.RuntimeError"
    assert "secret" not in str(result)


def test_wrong_profile_and_execution_error_fail_closed(monkeypatch) -> None:
    wrong = smoke.run_platform_ag_trace_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    assert wrong["status"] == "FAIL"
    assert wrong["failure_code"] == "profile_not_allowed"

    monkeypatch.setattr(
        smoke,
        "resolve_postgres_test_targets",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    failed = smoke.run_platform_ag_trace_postgres_smoke(
        {smoke.SMOKE_ENV: "1"},
        migration_runner=lambda _env: _migration_result(),
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "execution_failed.RuntimeError"
    assert "secret detail" not in str(failed)


def test_failed_checks_and_summary_paths(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke, "resolve_postgres_test_targets", lambda *_a, **_k: _targets()
    )
    failed_journey = {**_journey(), "stage_families": ["AUTH"]}
    result = smoke.run_platform_ag_trace_postgres_smoke(
        {smoke.SMOKE_ENV: "1"},
        migration_runner=lambda _env: _migration_result(),
        journey_runner=lambda _targets: failed_journey,
    )
    assert result["status"] == "FAIL"
    assert result["failed_checks"] == ["all_stage_families_projected"]
    assert "families=1" in smoke.summary_line(result)
    skipped = smoke.run_platform_ag_trace_postgres_smoke({})
    assert "=skipped" in smoke.summary_line(skipped)

    monkeypatch.setattr(
        smoke,
        "run_platform_ag_trace_postgres_smoke",
        lambda: {"status": "PASS", "summary": {}, "next_slice": "1381"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "next=1381" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_ag_trace_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main(["--summary"]) == 1
