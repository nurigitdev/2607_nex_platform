from __future__ import annotations

import json
from pathlib import Path

import run_s123_oa_credential_session_security_closure as closure


def test_repository_s123_closure_passes() -> None:
    result = closure.run_s123_oa_credential_session_security_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S124"
    assert result["feature_readiness"] == "OA_CREDENTIAL_SESSION_SECURITY_READY"
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "deterministic_check_count": 43,
        "canonical_schema_count": 2,
        "protected_operation_count": 3,
        "postgres_event_count": 12,
        "postgres_revoked_session_count": 2,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S124"
    assert result["next_requirement_scope"] == (
        "oa_group_role_authorization_hardening"
    )


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "argon2id_with_legacy_adaptive_rehash",
        "atomic_timed_login_lockout",
        "random_idle_and_absolute_session_expiry",
        "credential_rotation_session_revocation",
        "privacy_safe_auth_security_events",
    )
    assert decision["deferred_scope"] == (
        "multi_factor_authentication",
        "self_service_password_reset_delivery",
        "oidc_saml_external_identity",
        "signed_service_tokens_and_jwks_verification",
    )
    assert decision["password_hash_default"] == "argon2id.v1"
    assert decision["legacy_hash_read"] == "pbkdf2_sha256.v1"
    assert decision["lockout_threshold"] == 5
    assert decision["lockout_duration_seconds"] == 900
    assert decision["session_entropy_bytes"] == 32
    assert decision["session_idle_ttl_seconds"] == 1800
    assert decision["password_rotation_revokes_sessions"] is True
    assert decision["auth_event_table"] == "oa_auth_events"
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False


def test_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s123_oa_credential_session_security_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["feature_readiness"] == "INCOMPLETE"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["summary"]["postgres_event_count"] == 0
    assert result["components"]["actual_postgres_evidence"] is False


def test_closure_fails_for_evidence_failure_and_identity_drift(monkeypatch) -> None:
    monkeypatch.setattr(closure, "run_rotation", lambda: {"status": "FAIL"})
    failed = closure.run_s123_oa_credential_session_security_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["rotation_revocation_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_rotation",
        lambda: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S123",
            "checks": {"ok": True},
            "summary": {
                "check_count": 7,
                "passed_check_count": 7,
                "reset_revoked": 1,
                "change_revoked": 1,
            },
        },
    )
    drifted = closure.run_s123_oa_credential_session_security_closure()
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
    passing = closure.run_s123_oa_credential_session_security_closure()
    assert closure.summary_line(passing) == (
        "s123_oa_credential_session_security_closure=pass evidence=9/9 "
        "components=5/5 operations=3 postgres_events=12 next=S124"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s123_oa_credential_session_security_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        closure,
        "run_s123_oa_credential_session_security_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
