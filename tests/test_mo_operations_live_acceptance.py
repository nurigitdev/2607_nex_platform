from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import run_mo_operations_live_acceptance as smoke


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        smoke.PROFILE_ENV: "test",
        "NEX_MO_PROVIDER_MODE": "live",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_mo_user:private-db-secret@127.0.0.1/"
            "nex_mo_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://dgx.example:9112/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-provider-key",
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_RERANKER_URL": "http://dgx.example:9113/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "private-provider-key",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
        "NEX_MO_VLLM_BASE_URL": "http://dgx.example:9111",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
        "NEX_MO_RUNTIME_OBSERVABILITY_MODE": "live",
        "NEX_MO_DGX_SSH_TARGET": "operator@dgx.example",
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
        "provider_success_count": 3,
        "model_match_count": 3,
        "telemetry_row_count": 3,
        "telemetry_request_count": 3,
        "api_status": 200,
        "operations_status": "READY",
        "provider_mode": "live",
        "ready_source_count": 4,
        "ready_capability_count": 3,
        "runtime_ready_capability_count": 3,
        "schema_error_count": 0,
        "api_redacted": True,
        "cleanup": {"deleted_telemetry_rows": 3, "residue": 0},
    }


def test_live_acceptance_is_explicitly_protected() -> None:
    result = smoke.run_mo_operations_live_acceptance({})

    assert result["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in result["skip_reason"]


def test_live_acceptance_rejects_profile_and_incomplete_admission() -> None:
    profile = smoke.run_mo_operations_live_acceptance(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )
    incomplete = smoke.run_mo_operations_live_acceptance(
        {smoke.ACTIVATION_ENV: "1", smoke.PROFILE_ENV: "test"}
    )

    assert profile["failure_code"] == "profile_not_allowed"
    assert incomplete["failure_code"] == "live_acceptance_not_admitted"
    assert incomplete["diagnostics"]["issues"]


def test_live_acceptance_accepts_complete_redacted_evidence() -> None:
    result = smoke.run_mo_operations_live_acceptance(
        _env(), exercise=lambda _url, _env: _observations()
    )
    serialized = json.dumps(result)

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "passed_check_count": 13,
        "check_count": 13,
        "provider_success_count": 3,
        "model_match_count": 3,
        "telemetry_row_count": 3,
        "ready_source_count": 4,
        "ready_capability_count": 3,
        "runtime_ready_capability_count": 3,
        "schema_error_count": 0,
    }
    assert result["next_slice"] == "1191"
    assert "private-provider-key" not in serialized
    assert "private-db-secret" not in serialized


def test_live_acceptance_fails_closed_for_drift_and_exception() -> None:
    observations = _observations()
    observations["runtime_ready_capability_count"] = 2
    drift = smoke.run_mo_operations_live_acceptance(
        _env(), exercise=lambda _url, _env: observations
    )
    crashed = smoke.run_mo_operations_live_acceptance(
        _env(),
        exercise=lambda _url, _env: (_ for _ in ()).throw(
            RuntimeError("private detail")
        ),
    )

    assert drift["status"] == "FAIL"
    assert drift["checks"]["all_runtime_models_healthy"] is False
    assert crashed["failure_code"] == "live_acceptance_execution_failed"
    assert crashed["diagnostics"] == {"exception_type": "RuntimeError"}


def test_live_acceptance_helpers_fail_closed_and_redact(tmp_path: Path) -> None:
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
    smoke.assert_evidence_redacted({"safe": True}, _env())
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted({"leak": "private-provider-key"}, _env())


def test_live_acceptance_summary_and_main_paths(monkeypatch, capsys) -> None:
    skipped = smoke.run_mo_operations_live_acceptance({})
    passing = smoke.run_mo_operations_live_acceptance(
        _env(), exercise=lambda _url, _env: _observations()
    )
    assert smoke.summary_line(skipped).startswith(
        "mo_operations_live_acceptance=skipped"
    )
    assert smoke.summary_line(passing) == (
        "mo_operations_live_acceptance=pass checks=13/13 providers=3/3 "
        "models=3/3 sources=4/4 runtime=3/3 cleanup=0 next=1191"
    )
    monkeypatch.setattr(smoke, "run_mo_operations_live_acceptance", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "checks=13/13" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_mo_operations_live_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected live acceptance",
)
def test_protected_live_acceptance_uses_actual_postgres_and_dgx() -> None:
    result = smoke.run_mo_operations_live_acceptance()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
