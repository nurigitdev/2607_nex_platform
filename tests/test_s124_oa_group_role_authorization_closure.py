from __future__ import annotations

import json
from pathlib import Path

import run_s124_oa_group_role_authorization_closure as closure


def test_repository_s124_closure_passes() -> None:
    result = closure.run_s124_oa_group_role_authorization_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S125"
    assert result["feature_readiness"] == "OA_GROUP_ROLE_AUTHORIZATION_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "deterministic_check_count": 56,
        "canonical_schema_count": 6,
        "protected_operation_count": 8,
        "postgres_event_count": 5,
        "postgres_revoked_session_count": 2,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S125"
    assert result["next_requirement_scope"] == "pending_canonical_scope_review"


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "tenant_scoped_role_group_assignment_lifecycle",
        "allow_only_set_union_effective_authorization",
        "optimistic_revision_and_privacy_safe_events",
        "authorization_change_session_revocation",
        "dedicated_bootstrap_admin_and_read_scopes",
        "strict_contract_and_actual_postgres_evidence",
    )
    assert decision["deferred_scope"] == (
        "explicit_deny_rules",
        "nested_groups",
        "signed_service_tokens_and_jwks_verification",
    )
    assert decision["grant_composition"] == "set_union"
    assert decision["explicit_deny_supported"] is False
    assert decision["nested_groups_supported"] is False
    assert decision["authorization_change_revokes_sessions"] is True
    assert decision["admin_scope"] == "authorization:admin"
    assert decision["read_scope"] == "authorization:read"
    assert decision["bootstrap_scope"] == "identity:bootstrap:write"
    assert decision["authorization_tables"] == (
        "oa_roles",
        "oa_groups",
        "oa_group_members",
        "oa_group_roles",
        "oa_authz_events",
    )
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s124_oa_group_role_authorization_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_event_count"] == 0
    assert result["components"]["actual_postgres_evidence"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_repository", lambda: {"status": "FAIL"})
    failed = closure.run_s124_oa_group_role_authorization_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["domain_and_persistence_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_repository",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S124",
            "checks": {"ok": True},
            "summary": {
                "check_count": 6,
                "passed_check_count": 6,
                "record_count": 4,
                "event_count": 4,
            },
        },
    )
    drifted = closure.run_s124_oa_group_role_authorization_closure()
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
    passing = closure.run_s124_oa_group_role_authorization_closure()
    assert closure.summary_line(passing) == (
        "s124_oa_group_role_authorization_closure=pass evidence=9/9 "
        "components=5/5 operations=8 postgres_events=5 next=S125"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s124_oa_group_role_authorization_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s124_oa_group_role_authorization_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
