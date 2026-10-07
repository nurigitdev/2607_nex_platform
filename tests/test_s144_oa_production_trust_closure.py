from __future__ import annotations

from pathlib import Path

import run_s144_oa_production_trust_closure as closure


def test_repository_closure_passes_and_hands_off_to_s148() -> None:
    result = closure.run_s144_oa_production_trust_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S148"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "check_count": 15,
        "passed_check_count": 15,
        "gap_count": 8,
        "transit_version_count": 2,
        "oidc_jwks_key_count": 2,
        "managed_route_count": 10,
        "protected_database_count": 1,
    }
    assert result["decision"] == {
        "single_host_acceptance_passed": True,
        "source_controlled_attestation_present": True,
        "raw_protected_report_tracked": False,
        "additional_host_software_install_required": False,
        "corporate_idp_contacted": False,
        "registry_push_performed": False,
        "production_resources_contacted": False,
        "production_deployment_approved": False,
        "browser_callback_deferred_to_s149": True,
        "full_gate_registered": True,
        "next_requirement": "S145",
        "s148_dependency_ready": True,
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s144_oa_production_trust_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["decision"]["single_host_acceptance_passed"] is False
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["decision"]["s148_dependency_ready"] is False
    assert result["failed_checks"]


def test_helpers_cover_evidence_configuration_and_noncanonical_root(
    tmp_path: Path,
) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    assert closure._read_text(source) == '{"ok": true}'
    assert closure._read_text(tmp_path / "missing.md") == ""
    assert closure._load_json(source) == {"ok": True}
    source.write_text("not-json", encoding="utf-8")
    assert closure._load_json(source) == {}
    assert closure._load_json(tmp_path / "missing.json") == {}
    assert closure._configuration_digest(tmp_path) == ""

    evidence = {"status": "PASS", "evidence_digest": "old"}
    digest = closure._evidence_digest(evidence)
    assert digest.startswith("sha256:")
    assert digest == closure._evidence_digest(
        {"status": "PASS", "evidence_digest": "different"}
    )
    assert closure._summary({"one": {"summary": {"count": 1}}}, "one") == {
        "count": 1
    }
    assert closure._summary({}, "missing") == {}


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_audit_count": 8,
            "audit_count": 8,
            "gap_count": 8,
            "transit_version_count": 2,
            "oidc_jwks_key_count": 2,
            "managed_route_count": 10,
            "protected_database_count": 1,
        },
        "decision": {"next_requirement": "S145"},
    }
    assert closure.summary_line(passing) == (
        "s144_oa_production_trust_closure=pass audits=8/8 gaps=8 "
        "transit_versions=2 oidc_jwks=2 routes=10 databases=1 next=S145"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s144_oa_production_trust_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s144_oa_production_trust_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S145" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s144_oa_production_trust_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
