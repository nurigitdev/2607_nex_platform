from __future__ import annotations

import json
from pathlib import Path

import run_oa_production_trust_boundary as boundary


def test_repository_production_trust_boundary_passes() -> None:
    result = boundary.run_oa_production_trust_boundary()

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["decision"] == {
        "owner": "nex-oa",
        "trust_scope": "oa_fr_002_through_005_production_trust",
        "browser_session_profile": "opaque_oa_backed",
        "signed_token_profiles": (
            "service_access",
            "delegated_user_access",
        ),
        "production_mock_token_fallback": False,
        "test_profile_mock_token_compatibility": True,
        "local_signature_verification_required": True,
        "revocation_sensitive_introspection_required": True,
        "private_key_plaintext_database_storage_allowed": False,
        "actual_test_database_evidence_required": True,
        "protected_live_provider_evidence_required": False,
        "new_table_required": False,
        "existing_oa_records_mutated": False,
        "deferred_scope": (
            "external_oidc_or_saml",
            "multi_factor_authentication",
            "self_service_password_recovery_delivery",
            "hardware_security_module_integration",
            "explicit_deny_and_nested_group_authorization",
        ),
        "next_requirement": "S126",
        "decision_status": "FROZEN",
    }
    assert len(result["audit_surfaces"]) == 8
    assert len(result["slice_plan"]) == 10
    assert result["quality_cadence"] == {
        "slice_gate": "1242-1250",
        "checkpoint_gate": "1246",
        "full_gate": "1251",
    }


def test_boundary_fails_closed_when_evidence_is_missing(tmp_path: Path) -> None:
    result = boundary.run_oa_production_trust_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_production_trust_boundary_failed"
    assert result["checks"]["required_evidence_present"] is False
    assert len(result["issues"]) == len(boundary.REQUIRED_EVIDENCE)
    assert {item["category"] for item in result["issues"]} == {
        "evidence_missing"
    }


def test_read_text_handles_present_and_missing_files(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.write_text("trust", encoding="utf-8")

    assert boundary._read_text(present) == "trust"
    assert boundary._read_text(tmp_path / "missing") == ""


def test_summary_reports_pass_and_failure() -> None:
    passing = boundary.run_oa_production_trust_boundary()
    assert boundary.summary_line(passing) == (
        "oa_production_trust_boundary=pass profiles=2 "
        "browser=opaque_oa_backed mock_prod=False postgres=True next=S126"
    )
    assert boundary.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    ) == "oa_production_trust_boundary=fail issues=1"


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = boundary.run_oa_production_trust_boundary()
    monkeypatch.setattr(
        boundary,
        "run_oa_production_trust_boundary",
        lambda: passing,
    )

    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        boundary,
        "run_oa_production_trust_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
