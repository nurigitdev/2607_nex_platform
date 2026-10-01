from __future__ import annotations

import json
from pathlib import Path

import run_s122_oa_identity_membership_lifecycle_closure as closure


def test_repository_s122_closure_passes() -> None:
    result = closure.run_s122_oa_identity_membership_lifecycle_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S123"
    assert result["feature_readiness"] == (
        "OA_DIRECT_IDENTITY_MEMBERSHIP_LIFECYCLE_READY"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "subject_transition_check_count": 5,
        "membership_transition_check_count": 4,
        "canonical_schema_count": 2,
        "protected_operation_count": 2,
        "postgres_event_count": 2,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S123"
    assert result["next_requirement_scope"] == (
        "oa_credential_and_session_security_hardening"
    )


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["subject_states"] == ("ACTIVE", "DISABLED", "DELETED")
    assert decision["membership_states"] == ("ACTIVE", "DISABLED")
    assert decision["completed_scope"] == (
        "durable_subject_lifecycle",
        "durable_direct_membership_lifecycle",
        "atomic_session_revocation",
    )
    assert decision["deferred_scope"] == (
        "group_registry_and_group_membership",
        "dedicated_bootstrap_admin_authorization",
        "credential_rotation_rehash_and_lockout",
        "service_token_signing_and_jwks_verification",
    )
    assert decision["concurrency"] == "expected_revision_optimistic_guard"
    assert decision["audit_lineage"] == "append_only_server_actor_event"
    assert decision["session_policy"] == (
        "revoke_on_disable_or_delete_never_restore"
    )
    assert decision["table"] == "oa_id_lifecycle_events"
    assert decision["postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s122_oa_identity_membership_lifecycle_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_event_count"] == 0
    assert result["components"]["actual_postgres_evidence"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_cascade", lambda: {"status": "FAIL"})
    failed = closure.run_s122_oa_identity_membership_lifecycle_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["deprovision_cascade_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_cascade",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S122",
            "checks": {"ok": True},
            "revoked_session_count": 1,
        },
    )
    drifted = closure.run_s122_oa_identity_membership_lifecycle_closure()
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
    passing = closure.run_s122_oa_identity_membership_lifecycle_closure()
    assert closure.summary_line(passing) == (
        "s122_oa_identity_membership_lifecycle_closure=pass evidence=9/9 "
        "components=5/5 operations=2 postgres_events=2 next=S123"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s122_oa_identity_membership_lifecycle_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s122_oa_identity_membership_lifecycle_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
