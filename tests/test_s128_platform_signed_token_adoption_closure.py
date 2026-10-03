from __future__ import annotations

from pathlib import Path

import run_s128_platform_signed_token_adoption_closure as closure


def test_repository_s128_closure_passes(monkeypatch) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    result = closure.run_s128_platform_signed_token_adoption_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S129"
    assert result["service_access_adoption_readiness"] == (
        "PLATFORM_ADOPTION_READY"
    )
    assert result["production_signed_only_activation"] == (
        "PROFILE_CONFIGURATION_REQUIRED"
    )
    assert all(result["checks"].values())
    assert all(result["components"].values())
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 9,
        "component_count": 5,
        "closed_component_count": 5,
        "consumer_count": 4,
        "runtime_schema_count": 1,
        "postgres_migration_count": 16,
        "postgres_issued_token_count": 4,
        "postgres_cleanup_residue_count": 0,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert result["next_requirement"] == "S129"
    assert result["next_requirement_scope"] == "pending_canonical_scope_review"


def test_closure_freezes_completed_and_deferred_scope() -> None:
    decision = closure._closure_decision()

    assert decision["completed_scope"] == (
        "shared_rs256_jwks_verification_and_bounded_cache",
        "shared_fastapi_admission_and_sensitive_route_introspection",
        "ae_cx_mo_ag_service_access_adoption",
        "protected_redacted_rollout_observability",
        "actual_postgres_four_consumer_loopback_evidence",
    )
    assert decision["implementation_readiness"] == "READY"
    assert decision["production_signed_only_activation"] == (
        "PROFILE_CONFIGURATION_REQUIRED"
    )
    assert decision["delegated_user_access"] == "DEFERRED"
    assert decision["next_requirement"] == "S129"
    assert decision["actual_postgres_smoke_required"] is True
    assert decision["remote_provider_calls_required"] is False
    assert decision["new_tables_created"] == ()


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s128_platform_signed_token_adoption_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["service_access_adoption_readiness"] == "INCOMPLETE"
    assert result["production_signed_only_activation"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(
        closure.REQUIRED_FILES
    )
    assert result["summary"]["missing_token_count"] == len(
        closure.TOKEN_CHECKS
    )
    assert result["summary"]["postgres_migration_count"] == 0
    assert result["summary"]["postgres_cleanup_residue_count"] == -1
    assert result["components"]["actual_postgres_platform_loopback"] is False
    assert result["next_requirement"] == "blocked"


def test_closure_fails_for_evidence_failure_and_identity_drift(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    monkeypatch.setattr(closure, "run_ag", lambda _root: {"status": "FAIL"})
    failed = closure.run_s128_platform_signed_token_adoption_closure()
    assert failed["status"] == "FAIL"
    assert failed["checks"]["all_evidence_passed"] is False
    assert failed["checks"]["consumer_adoption_closed"] is False

    monkeypatch.setattr(
        closure,
        "run_ag",
        lambda _root: {
            "status": "PASS",
            "slice": "9999",
            "requirement": "S128",
        },
    )
    drifted = closure.run_s128_platform_signed_token_adoption_closure()
    assert drifted["status"] == "FAIL"
    assert drifted["checks"]["evidence_identity_complete"] is False


def test_postgres_evidence_prefers_live_when_explicitly_enabled(
    monkeypatch,
) -> None:
    expected = {
        "status": "PASS",
        "slice": "1280",
        "requirement": "S128",
        "summary": {"migration_count": 16},
    }
    monkeypatch.setenv(closure.SMOKE_ENV, "1")
    monkeypatch.setattr(closure, "run_postgres", lambda: expected)

    assert closure._postgres_evidence(closure.ROOT, {}) == expected


def test_postgres_evidence_requires_complete_recorded_tokens(
    monkeypatch,
) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    failed = closure._postgres_evidence(closure.ROOT, {})

    assert failed["status"] == "FAIL"
    assert failed["summary"]["cleanup_residue_count"] == -1


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
    assert closure._repository_evidence(tmp_path, lambda: {"status": "PASS"}) == {
        "status": "FAIL",
        "failure_code": "repository_root_invalid",
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    monkeypatch.delenv(closure.SMOKE_ENV, raising=False)
    passing = closure.run_s128_platform_signed_token_adoption_closure()
    assert closure.summary_line(passing) == (
        "s128_platform_signed_token_adoption_closure=pass evidence=9/9 "
        "components=5/5 consumers=4 "
        "activation=PROFILE_CONFIGURATION_REQUIRED next=S129"
    )
    monkeypatch.setattr(
        closure,
        "run_s128_platform_signed_token_adoption_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S129" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s128_platform_signed_token_adoption_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
