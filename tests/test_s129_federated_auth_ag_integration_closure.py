from __future__ import annotations

from pathlib import Path

import run_s129_federated_auth_ag_integration_closure as closure


def test_repository_s129_closure_passes(monkeypatch) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    result = closure.run_s129_federated_auth_ag_integration_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S130"
    assert result["federation_integration_readiness"] == (
        "OA_AG_INTEGRATION_READY"
    )
    assert result["production_activation"] == (
        "DEPLOYMENT_CONFIGURATION_REQUIRED"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "federation_table_count": 2,
        "canonical_schema_count": 163,
        "postgres_migration_count": 17,
        "postgres_tls_request_count": 2,
        "postgres_cleanup_residue_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S130"
    assert result["next_requirement_scope"] == "pending_canonical_scope_review"


def test_closure_freezes_completed_and_deployment_scope() -> None:
    decision = closure._closure_decision()

    assert decision["implementation_readiness"] == "READY"
    assert decision["external_idp_registration"] == (
        "DEPLOYMENT_CONFIGURATION_REQUIRED"
    )
    assert decision["browser_pkce_redirect_callback"] == (
        "PRODUCT_INTEGRATION_REQUIRED"
    )
    assert decision["external_live_idp_acceptance"] == (
        "DEPLOYMENT_ENVIRONMENT_REQUIRED"
    )
    assert decision["saml_2_0"] == "DEFERRED"
    assert decision["delegated_user_access"] == "DEFERRED"
    assert decision["cross_service_database_reads_allowed"] is False
    assert decision["remote_model_provider_required"] is False
    assert decision["next_requirement"] == "S130"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s129_federated_auth_ag_integration_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["federation_integration_readiness"] == "INCOMPLETE"
    assert result["production_activation"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(
        closure.REQUIRED_FILES
    )
    assert result["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert result["summary"]["postgres_migration_count"] == 0
    assert result["summary"]["postgres_cleanup_residue_count"] == -1
    assert result["components"]["actual_postgres_tls_loopback"] is False
    assert result["next_requirement"] == "blocked"


def test_closure_fails_for_evidence_failure_and_identity_drift(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    monkeypatch.setattr(
        closure,
        "run_ag_authorization",
        lambda: {"status": "FAIL"},
    )
    failed = closure.run_s129_federated_auth_ag_integration_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["oa_session_and_ag_context_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_ag_authorization",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S129",
        },
    )
    drifted = closure.run_s129_federated_auth_ag_integration_closure()
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["evidence_identity_complete"] is False


def test_postgres_evidence_prefers_live_when_explicitly_enabled(
    monkeypatch,
) -> None:
    expected = {
        "status": "PASS",
        "slice": "1290",
        "requirement": "S129",
        "summary": {"migration_count": 17},
    }
    monkeypatch.setenv(closure.SMOKE_ENV, "1")
    monkeypatch.setattr(closure, "run_postgres", lambda: expected)

    assert closure._postgres_evidence(closure.ROOT, {}) == expected


def test_postgres_document_fallback_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    failed = closure._postgres_evidence(closure.ROOT, {})

    assert failed["status"] == "FAIL"
    assert failed["summary"]["cleanup_residue_count"] == -1


def test_repository_and_safe_evidence_failure_helpers(tmp_path: Path) -> None:
    assert closure._repository_evidence(tmp_path, lambda: {"status": "PASS"}) == {
        "status": "FAIL",
        "failure_code": "repository_root_invalid",
    }
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping([]) == {}
    assert closure._read_text(tmp_path / "missing") == ""


def test_summary_and_main(monkeypatch, capsys) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    evidence = closure.run_s129_federated_auth_ag_integration_closure()
    assert closure.summary_line(evidence) == (
        "s129_federated_auth_ag_integration_closure=pass "
        "evidence=9/9 components=5/5 migrations=17 "
        "activation=DEPLOYMENT_CONFIGURATION_REQUIRED next=S130"
    )
    monkeypatch.setattr(
        closure,
        "run_s129_federated_auth_ag_integration_closure",
        lambda: evidence,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S130" in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s129_federated_auth_ag_integration_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
