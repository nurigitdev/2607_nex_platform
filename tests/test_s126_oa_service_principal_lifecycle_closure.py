from __future__ import annotations

from pathlib import Path

import run_s126_oa_service_principal_lifecycle_closure as closure


def test_repository_s126_closure_passes() -> None:
    result = closure.run_s126_oa_service_principal_lifecycle_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S127"
    assert result["service_principal_readiness"] == "OA_SERVICE_PRINCIPAL_READY"
    assert result["signed_token_runtime_readiness"] == "DEFERRED_TO_S127"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "lifecycle_table_count": 2,
        "canonical_schema_count": 6,
        "protected_operation_count": 9,
        "postgres_migration_count": 15,
        "postgres_cleanup_residue_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S127"
    assert result["next_requirement_scope"] == (
        "oa_signed_token_runtime_and_key_lifecycle"
    )


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "oa_owned_service_principal_registry_and_allowlists",
        "durable_argon2id_client_credential_lifecycle",
        "one_time_issue_rotation_revocation_and_verification",
        "protected_read_admin_api_contracts_and_privacy",
        "actual_postgres_restart_and_cleanup_evidence",
    )
    assert decision["s127_scope"] == (
        "signing_key_and_revocation_lifecycle",
        "client_credential_token_exchange",
        "jwks_and_introspection_runtime",
        "signed_only_cross_service_rollout",
    )
    assert decision["service_principal_readiness"] == "READY"
    assert decision["signed_token_runtime_readiness"] == "DEFERRED_TO_S127"
    assert decision["next_requirement"] == "S127"
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False
    assert decision["new_tables_created"] == (
        "oa_service_principals",
        "oa_service_creds",
    )


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s126_oa_service_principal_lifecycle_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["service_principal_readiness"] == "INCOMPLETE"
    assert result["signed_token_runtime_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_migration_count"] == 0
    assert result["summary"]["postgres_cleanup_residue_count"] == -1
    assert result["components"]["actual_postgres"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    monkeypatch.setattr(closure, "run_contracts", lambda _root: {"status": "FAIL"})
    failed = closure.run_s126_oa_service_principal_lifecycle_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["contracts_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_contracts",
        lambda _root: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S126",
            "summary": {
                "schema_count": 6,
                "privacy_safe_count": 6,
                "runtime_valid_count": 6,
                "operation_valid_count": 9,
                "remaining_contract_drift_count": 22,
            },
        },
    )
    drifted = closure.run_s126_oa_service_principal_lifecycle_closure()
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["evidence_identity_complete"] is False


def test_postgres_evidence_prefers_live_when_explicitly_enabled(monkeypatch) -> None:
    expected = {
        "status": "PASS",
        "slice": "1260",
        "requirement": "S126",
        "summary": {"migration_count": 15},
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
    static = closure._static_slice_evidence(tmp_path, "1253", "present.txt")
    assert static["status"] == "PASS"
    assert closure._static_slice_evidence(tmp_path, "1253", "missing")[
        "status"
    ] == "FAIL"
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
    passing = closure.run_s126_oa_service_principal_lifecycle_closure()
    assert closure.summary_line(passing) == (
        "s126_oa_service_principal_lifecycle_closure=pass evidence=9/9 "
        "components=5/5 operations=9 runtime=DEFERRED_TO_S127 next=S127"
    )
    monkeypatch.setattr(
        closure,
        "run_s126_oa_service_principal_lifecycle_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S127" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s126_oa_service_principal_lifecycle_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
