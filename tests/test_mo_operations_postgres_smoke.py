from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import run_mo_operations_postgres_smoke as smoke


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_mo_user:private-db-secret@127.0.0.1/"
            "nex_mo_test"
        ),
    }


def _observations() -> dict[str, object]:
    return {
        "database_identity": {
            "database_name": "nex_mo_test",
            "database_user": "nex_mo_user",
        },
        "migration": {
            "planned_count": 9,
            "applied_count": 0,
            "skipped_count": 9,
            "profile": "test",
        },
        "migrations_current": True,
        "table_count": 3,
        "active_alias_count": 3,
        "telemetry_row_count": 3,
        "telemetry_request_count": 3,
        "restart_recovered": True,
        "unauthorized_status": 401,
        "api_status": 200,
        "operations_status": "READY",
        "ready_source_count": 4,
        "ready_capability_count": 3,
        "projected_request_count": 3,
        "schema_error_count": 0,
        "api_redacted": True,
        "cleanup": {"deleted_telemetry_rows": 3, "residue": 0},
    }


def test_operations_postgres_smoke_is_explicitly_protected() -> None:
    result = smoke.run_mo_operations_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in result["skip_reason"]


def test_operations_postgres_smoke_rejects_invalid_configuration() -> None:
    profile = smoke.run_mo_operations_postgres_smoke(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    missing = smoke.run_mo_operations_postgres_smoke({smoke.ACTIVATION_ENV: "1"})
    wrong = smoke.run_mo_operations_postgres_smoke(
        {
            smoke.ACTIVATION_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_mo_user:secret@127.0.0.1/nex_mo_dev"
            ),
        }
    )

    assert profile["failure_code"] == "profile_not_allowed"
    assert missing["diagnostics"]["missing_env"] == [smoke.DATABASE_ENV]
    assert wrong["failure_code"] == "database_target_not_allowed"


def test_operations_postgres_smoke_accepts_complete_redacted_evidence() -> None:
    result = smoke.run_mo_operations_postgres_smoke(
        _env(), exercise=lambda _url: _observations()
    )
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 16,
        "check_count": 16,
        "planned_migration_count": 9,
        "applied_migration_count": 0,
        "skipped_migration_count": 9,
        "persisted_telemetry_count": 3,
        "ready_source_count": 4,
        "ready_capability_count": 3,
    }
    assert result["next_slice"] == "1190"
    assert "private-db-secret" not in serialized


def test_operations_postgres_smoke_fails_closed() -> None:
    observations = _observations()
    observations["ready_source_count"] = 3
    drift = smoke.run_mo_operations_postgres_smoke(
        _env(), exercise=lambda _url: observations
    )
    crashed = smoke.run_mo_operations_postgres_smoke(
        _env(),
        exercise=lambda _url: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    assert drift["status"] == "FAIL"
    assert drift["checks"]["all_sources_ready"] is False
    assert crashed["failure_code"] == "postgres_execution_failed"
    assert crashed["diagnostics"] == {"exception_type": "RuntimeError"}


def test_operations_postgres_smoke_helpers_and_redaction(tmp_path: Path) -> None:
    assert smoke._database_target(_env()[smoke.DATABASE_ENV]) == {
        "backend": "postgresql",
        "database_name": "nex_mo_test",
        "database_user": "nex_mo_user",
    }
    assert smoke._database_target("not a url")["backend"] is None
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.json"
    sequence = tmp_path / "sequence.json"
    valid.write_text('{"ok": true}', encoding="utf-8")
    invalid.write_text("{", encoding="utf-8")
    sequence.write_text("[]", encoding="utf-8")
    assert smoke._read_json(valid) == {"ok": True}
    assert smoke._read_json(invalid) == {}
    assert smoke._read_json(sequence) == {}
    assert smoke._read_json(tmp_path / "missing.json") == {}
    assert smoke._json_object({"ok": True}) == {"ok": True}
    with pytest.raises(ValueError, match="response_not_json_object"):
        smoke._json_object([])
    assert smoke._mapping(None) == {}
    assert smoke._nonnegative_int(2) == 2
    assert smoke._nonnegative_int(-1) == 0
    smoke.assert_evidence_redacted({"safe": True}, _env()[smoke.DATABASE_ENV])
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted(
            {"leak": "private-db-secret"},
            _env()[smoke.DATABASE_ENV],
        )


def test_operations_postgres_smoke_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_mo_operations_postgres_smoke(
        _env(), exercise=lambda _url: _observations()
    )
    assert smoke.summary_line(passing) == (
        "mo_operations_postgres_smoke=pass checks=16/16 "
        "migrations=0+9/9 telemetry=3 ready=4/4+3/3 cleanup=0 next=1190"
    )
    monkeypatch.setattr(smoke, "run_mo_operations_postgres_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=16/16" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_mo_operations_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected PostgreSQL smoke",
)
def test_protected_operations_postgres_smoke_uses_actual_nex_mo_test() -> None:
    result = smoke.run_mo_operations_postgres_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
