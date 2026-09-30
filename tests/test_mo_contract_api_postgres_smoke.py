from __future__ import annotations

import json
import os

import pytest

import run_mo_contract_api_postgres_smoke as smoke


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
            "planned_count": 7,
            "applied_count": 0,
            "skipped_count": 7,
            "recorded_count": 7,
            "profile": "test",
        },
        "migrations_current": True,
        "persistence_mode": "postgres",
        "job_store_round_trip": True,
        "job_read_status": 200,
        "job_cancel_status": 200,
        "job_cancelled_in_database": True,
        "service_log_round_trip": True,
        "purge_status": 200,
        "candidate_count": 1,
        "history_list_status": 200,
        "history_list_contains_execution": True,
        "history_detail_status": 200,
        "unauthorized_status": 401,
        "cleanup": {
            "service_jobs": 1,
            "service_log_entries": 1,
            "retention_history": 1,
            "residue": 0,
        },
    }


def test_postgres_smoke_is_explicitly_protected() -> None:
    result = smoke.run_mo_contract_api_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in result["skip_reason"]


def test_postgres_smoke_rejects_profile_configuration_and_database_target() -> None:
    profile = smoke.run_mo_contract_api_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    missing = smoke.run_mo_contract_api_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )
    wrong = smoke.run_mo_contract_api_postgres_smoke(
        {
            smoke.ACTIVATION_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://nex_mo_user:secret@localhost/nex_mo_dev",
        }
    )

    assert profile["failure_code"] == "profile_not_allowed"
    assert missing["diagnostics"]["missing_env"] == [smoke.DATABASE_ENV]
    assert wrong["failure_code"] == "database_target_not_allowed"


def test_postgres_smoke_accepts_complete_redacted_evidence() -> None:
    result = smoke.run_mo_contract_api_postgres_smoke(
        _env(),
        exercise=lambda _url: _observations(),
    )
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 12,
        "check_count": 12,
        "planned_migration_count": 7,
        "applied_migration_count": 0,
        "skipped_migration_count": 7,
        "database_write_count": 3,
        "api_request_count": 6,
    }
    assert result["next_slice"] == "1141"
    assert "private-db-secret" not in serialized


def test_postgres_smoke_fails_closed_for_observation_or_execution_failure() -> None:
    observations = _observations()
    observations["job_read_status"] = 503
    failed = smoke.run_mo_contract_api_postgres_smoke(
        _env(), exercise=lambda _url: observations
    )
    crashed = smoke.run_mo_contract_api_postgres_smoke(
        _env(),
        exercise=lambda _url: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    assert failed["status"] == "FAIL"
    assert failed["checks"]["job_api_read_succeeded"] is False
    assert crashed["failure_code"] == "postgres_execution_failed"
    assert crashed["diagnostics"] == {"exception_type": "RuntimeError"}


def test_postgres_smoke_helpers_and_redaction() -> None:
    assert smoke._database_target(_env()[smoke.DATABASE_ENV]) == {
        "backend": "postgresql",
        "database_name": "nex_mo_test",
        "database_user": "nex_mo_user",
    }
    assert smoke._database_target("not a url")["database_name"] is None
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
    passing = smoke.run_mo_contract_api_postgres_smoke(
        _env(), exercise=lambda _url: _observations()
    )
    assert smoke.summary_line(passing) == (
        "mo_contract_api_postgres_smoke=pass checks=12/12 "
        "migrations=0+7/7 writes=3 cleanup=0 next=1141"
    )
    monkeypatch.setattr(smoke, "run_mo_contract_api_postgres_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=12/12" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_mo_contract_api_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected PostgreSQL smoke",
)
def test_protected_postgres_smoke_uses_actual_nex_mo_test() -> None:
    result = smoke.run_mo_contract_api_postgres_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
