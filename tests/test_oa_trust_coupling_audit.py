from __future__ import annotations

from pathlib import Path

from nex_oa.trust_coupling_audit import (
    RequiredEvidence,
    _control,
    _inspect_evidence,
    _read_text,
    build_oa_trust_coupling_audit,
)
import run_oa_trust_coupling_audit as runner


def test_repository_trust_coupling_audit_orders_refactoring() -> None:
    result = build_oa_trust_coupling_audit()

    assert result["status"] == "PASS"
    assert result["trust_readiness"] == (
        "ORDERED_REFACTOR_REQUIRED_BEFORE_PRODUCTION_AUTH"
    )
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "control_count": 8,
        "explicit_boundary_count": 3,
        "refactor_required_count": 3,
        "hardened_count": 2,
        "high_risk_count": 2,
        "evidence_issue_count": 0,
    }
    assert result["decision"]["direct_cross_database_reads_forbidden"] is True
    assert result["decision"]["mock_token_fallback_production_forbidden"] is True


def test_trust_observations_separate_boundaries_from_risks() -> None:
    observations = build_oa_trust_coupling_audit()["observations"]

    assert observations["explicit_ae_oa_http_adapter_present"] is True
    assert observations["explicit_cx_oa_http_adapter_present"] is True
    assert observations["claim_authoritative_owner_scope_present"] is True
    assert observations["mock_service_token_fallback_present"] is True
    assert observations["generic_service_scope_used_for_internal_routes"] is False
    assert observations["signed_internal_admission_present"] is True
    assert observations["resolver_transport_detail_exposure_present"] is False
    assert observations["cross_service_retry_policy_present"] is False
    assert observations["browser_cookie_secure_by_default"] is False
    assert observations["oa_auth_mode_default_by_default"] is False


def test_trust_audit_fails_closed_without_repository(tmp_path: Path) -> None:
    result = build_oa_trust_coupling_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["trust_readiness"] == "BLOCKED"
    assert result["checks"]["required_evidence_present"] is False
    assert result["checks"]["explicit_boundaries_observed"] is False
    assert result["checks"]["current_coupling_gaps_observed"] is False
    assert result["issues"][-1] == {
        "category": "trust_coupling_classification_drift"
    }


def test_helpers_cover_present_missing_and_control_shapes(tmp_path: Path) -> None:
    path = tmp_path / "evidence.txt"
    path.write_text("token\n", encoding="utf-8")
    ref = RequiredEvidence("sample", "evidence.txt", "token")

    assert _inspect_evidence(tmp_path, ref)["present"] is True
    assert _read_text(path) == "token\n"
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _control("sample", "REFACTOR_REQUIRED", "HIGH", "reason") == {
        "control_id": "sample",
        "status": "REFACTOR_REQUIRED",
        "risk": "HIGH",
        "reason": "reason",
    }


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_trust_coupling_audit()

    assert "coupling_audit=pass" in runner.summary_line(passing)
    assert "explicit=3" in runner.summary_line(passing)
    assert "refactor=3" in runner.summary_line(passing)
    assert "hardened=2" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_oa_trust_coupling_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "high_risk=2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_oa_trust_coupling_audit",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
