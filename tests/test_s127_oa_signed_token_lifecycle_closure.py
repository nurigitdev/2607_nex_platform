from __future__ import annotations

from pathlib import Path

import run_s127_oa_signed_token_lifecycle_closure as closure


def test_repository_s127_closure_passes() -> None:
    result = closure.run_s127_oa_signed_token_lifecycle_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S128"
    assert result["signed_token_implementation_readiness"] == "OA_SIGNED_TOKEN_READY"
    assert result["production_signing_custody"] == "EXTERNAL_ADAPTER_REQUIRED"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "signed_runtime_table_count": 2,
        "canonical_schema_count": 4,
        "signed_operation_count": 4,
        "postgres_migration_count": 16,
        "postgres_cleanup_residue_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S128"
    assert result["next_requirement_scope"] == (
        "oa_production_signing_custody_and_cross_service_signed_token_rollout"
    )


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "external_reference_key_metadata_and_public_jwks",
        "durable_signing_key_and_digest_only_revocation_lifecycle",
        "rs256_client_credential_exchange_with_five_minute_tokens",
        "strict_validation_introspection_revocation_and_privacy_contracts",
        "actual_postgres_restart_and_cleanup_evidence",
    )
    assert decision["implementation_readiness"] == "READY"
    assert decision["production_signing_custody"] == "EXTERNAL_ADAPTER_REQUIRED"
    assert decision["cross_service_signed_only_rollout"] == "DEFERRED"
    assert decision["next_requirement"] == "S128"
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False
    assert decision["new_tables_created"] == (
        "oa_signing_keys",
        "oa_token_revocations",
    )


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s127_oa_signed_token_lifecycle_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["signed_token_implementation_readiness"] == "INCOMPLETE"
    assert result["production_signing_custody"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_migration_count"] == 0
    assert result["summary"]["postgres_cleanup_residue_count"] == -1
    assert result["components"]["actual_postgres"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    monkeypatch.setattr(closure, "run_validation", lambda: {"status": "FAIL"})
    failed = closure.run_s127_oa_signed_token_lifecycle_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["validation_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_validation",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S127",
            "active_before_revoke": True,
            "active_after_revoke": False,
        },
    )
    drifted = closure.run_s127_oa_signed_token_lifecycle_closure()
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["evidence_identity_complete"] is False


def test_api_contract_evidence_fails_for_missing_contracts(tmp_path: Path) -> None:
    evidence = closure._api_contract_evidence(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["api_status"] == "FAIL"
    assert evidence["summary"] == {
        "schema_count": 0,
        "positive_example_count": 0,
        "privacy_negative_count": 0,
        "operation_count": 0,
    }


def test_postgres_evidence_prefers_live_when_explicitly_enabled(monkeypatch) -> None:
    expected = {
        "status": "PASS",
        "slice": "1270",
        "requirement": "S127",
        "summary": {"migration_count": 16},
    }
    monkeypatch.setenv(closure.SMOKE_ENV, "1")
    monkeypatch.setattr(closure, "run_postgres", lambda: expected)

    assert closure._postgres_evidence(closure.ROOT, {}) == expected


def test_closure_helpers_fail_closed(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    path = tmp_path / "present.txt"
    path.write_text("evidence", encoding="utf-8")
    assert closure._read_text(path) == "evidence"
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    passing = closure.run_s127_oa_signed_token_lifecycle_closure()
    assert closure.summary_line(passing) == (
        "s127_oa_signed_token_lifecycle_closure=pass evidence=9/9 "
        "components=5/5 operations=4 custody=EXTERNAL_ADAPTER_REQUIRED next=S128"
    )
    monkeypatch.setattr(
        closure,
        "run_s127_oa_signed_token_lifecycle_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S128" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s127_oa_signed_token_lifecycle_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
