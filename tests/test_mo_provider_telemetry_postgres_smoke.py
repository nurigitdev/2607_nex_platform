from __future__ import annotations

import json
import os

import pytest

import run_mo_provider_telemetry_postgres_smoke as smoke


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.DATABASE_ENV: (
            "postgresql://nex_mo_user:private-db-secret@localhost/nex_mo_test"
        ),
    }


def _observations() -> dict[str, object]:
    return {
        "database_identity": {
            "database_name": "nex_mo_test",
            "database_user": "nex_mo_user",
        },
        "migration": {
            "planned_count": 8,
            "applied_count": 1,
            "skipped_count": 7,
            "profile": "test",
        },
        "migrations_current": True,
        "telemetry_table_present": True,
        "counts": {
            "request_count": 24,
            "success_count": 12,
            "failure_count": 12,
            "retryable_failure_count": 12,
            "degraded_count": 12,
            "attempt_count": 25,
            "retry_count": 1,
        },
        "restart_recovered": True,
        "latest_observed_at": "2026-09-30T12:00:24Z",
        "latest_outcome": "success",
        "unauthorized_status": 401,
        "api_status": 200,
        "api_counts_match": True,
        "api_redacted": True,
        "cleanup": {"deleted_count": 1, "residue": 0},
    }


def test_postgres_smoke_is_explicitly_protected() -> None:
    result = smoke.run_mo_provider_telemetry_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in result["skip_reason"]


def test_postgres_smoke_rejects_profile_missing_url_and_wrong_target() -> None:
    profile = smoke.run_mo_provider_telemetry_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    missing = smoke.run_mo_provider_telemetry_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )
    wrong = smoke.run_mo_provider_telemetry_postgres_smoke(
        {
            smoke.ACTIVATION_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_mo_user:secret@localhost/nex_mo_dev"
            ),
        }
    )

    assert profile["failure_code"] == "profile_not_allowed"
    assert missing["diagnostics"]["missing_env"] == [smoke.DATABASE_ENV]
    assert wrong["failure_code"] == "database_target_not_allowed"


def test_postgres_smoke_accepts_complete_redacted_evidence() -> None:
    result = smoke.run_mo_provider_telemetry_postgres_smoke(
        _env(), exercise=lambda _url: _observations()
    )
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 11,
        "check_count": 11,
        "planned_migration_count": 8,
        "applied_migration_count": 1,
        "skipped_migration_count": 7,
        "worker_count": 8,
        "mutation_count": 25,
        "request_count": 24,
        "attempt_count": 25,
        "api_request_count": 2,
    }
    assert result["next_slice"] == "1161"
    assert "private-db-secret" not in serialized


def test_postgres_smoke_fails_closed_for_drift_or_execution_failure() -> None:
    observations = _observations()
    observations["api_status"] = 503
    drift = smoke.run_mo_provider_telemetry_postgres_smoke(
        _env(), exercise=lambda _url: observations
    )
    crashed = smoke.run_mo_provider_telemetry_postgres_smoke(
        _env(),
        exercise=lambda _url: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    assert drift["status"] == "FAIL"
    assert drift["checks"]["authenticated_api_read_succeeded"] is False
    assert crashed["failure_code"] == "postgres_execution_failed"
    assert crashed["diagnostics"] == {"exception_type": "RuntimeError"}


def test_postgres_smoke_helpers_and_redaction() -> None:
    assert smoke._database_target(_env()[smoke.DATABASE_ENV]) == {
        "backend": "postgresql",
        "database_name": "nex_mo_test",
        "database_user": "nex_mo_user",
    }
    assert smoke._database_target("not a url")["backend"] is None
    assert smoke._json_object({"ok": True}) == {"ok": True}
    with pytest.raises(ValueError, match="response_not_json_object"):
        smoke._json_object([])
    assert smoke._mapping(None) == {}
    assert smoke._nonnegative_int(2) == 2
    assert smoke._nonnegative_int(-1) == 0
    smoke.assert_evidence_redacted({"safe": True}, _env()[smoke.DATABASE_ENV])
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted(
            {"leak": "private-db-secret"}, _env()[smoke.DATABASE_ENV]
        )


def test_postgres_smoke_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_provider_telemetry_postgres_smoke(
        _env(), exercise=lambda _url: _observations()
    )
    assert smoke.summary_line(passing) == (
        "mo_provider_telemetry_postgres_smoke=pass checks=11/11 "
        "migrations=1+7/8 mutations=25 requests=24 attempts=25 "
        "cleanup=0 next=1161"
    )
    monkeypatch.setattr(
        smoke, "run_mo_provider_telemetry_postgres_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=11/11" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_mo_provider_telemetry_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected PostgreSQL smoke",
)
def test_protected_postgres_smoke_uses_actual_nex_mo_test() -> None:
    result = smoke.run_mo_provider_telemetry_postgres_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
