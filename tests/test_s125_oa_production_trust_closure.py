from __future__ import annotations

import json
from pathlib import Path

import run_s125_oa_production_trust_closure as closure


def test_repository_s125_closure_passes() -> None:
    result = closure.run_s125_oa_production_trust_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S126"
    assert result["policy_readiness"] == "OA_PRODUCTION_TRUST_POLICY_READY"
    assert result["signed_runtime_readiness"] == "IMPLEMENTATION_PENDING"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "signed_profile_count": 2,
        "proposed_table_count": 4,
        "threat_count": 8,
        "postgres_migration_count": 14,
        "postgres_cleanup_residue_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S126"
    assert result["next_requirement_scope"] == (
        "oa_signed_token_runtime_implementation"
    )


def test_closure_freezes_decision_and_honest_runtime_state() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "oa_owned_trust_and_opaque_browser_session",
        "service_and_delegated_user_signed_token_profiles",
        "rs256_external_key_custody_and_rotation_policy",
        "fail_closed_jwks_introspection_and_revocation_semantics",
        "service_principal_and_signed_only_rollout_handoff",
        "privacy_threat_contracts_and_actual_postgres_baseline",
    )
    assert decision["s126_implementation_scope"] == (
        "durable_service_principal_credential_key_and_revocation_storage",
        "signed_token_exchange_jwks_and_introspection_runtime",
        "ordered_cross_service_signed_only_rollout",
    )
    assert decision["policy_readiness"] == "READY"
    assert decision["signed_runtime_readiness"] == "IMPLEMENTATION_PENDING"
    assert decision["implementation_requirement"] == "S126"
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False
    assert decision["new_tables_created_in_s125"] is False


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s125_oa_production_trust_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["policy_readiness"] == "INCOMPLETE"
    assert result["signed_runtime_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_migration_count"] == 0
    assert result["summary"]["postgres_cleanup_residue_count"] == -1
    assert result["components"]["actual_postgres_baseline"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_validation", lambda: {"status": "FAIL"})
    failed = closure.run_s125_oa_production_trust_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["validation_and_handoff_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_validation",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S125",
            "policy": {
                "jwks_cache_ttl_seconds": 300,
                "unknown_kid_refresh_attempts": 1,
                "introspection_timeout_seconds": 3,
                "stale_jwks_acceptance_allowed": False,
                "introspection_error_acceptance_allowed": False,
            },
        },
    )
    drifted = closure.run_s125_oa_production_trust_closure()
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["evidence_identity_complete"] is False


def test_closure_helpers_fail_closed(tmp_path: Path) -> None:
    assert closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private"))
    ) == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ok", encoding="utf-8")
    assert closure._read_text(present) == "ok"


def test_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s125_oa_production_trust_closure()
    assert closure.summary_line(passing) == (
        "s125_oa_production_trust_closure=pass evidence=9/9 "
        "components=5/5 profiles=2 runtime=IMPLEMENTATION_PENDING next=S126"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s125_oa_production_trust_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s125_oa_production_trust_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
