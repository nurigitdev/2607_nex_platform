from __future__ import annotations

from pathlib import Path

import run_s143_production_configuration_secret_tls_closure as closure


def test_repository_closure_passes_and_hands_off_to_s144_s147() -> None:
    result = closure.run_s143_production_configuration_secret_tls_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S144_S147"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 7,
        "passed_audit_count": 7,
        "check_count": 15,
        "passed_check_count": 15,
        "required_environment_count": 25,
        "secret_reference_count": 16,
        "compose_service_count": 9,
        "protected_database_count": 5,
        "protected_provider_count": 3,
        "managed_route_count": 9,
    }
    assert result["decision"] == {
        "external_staging_acceptance_passed": True,
        "source_controlled_attestation_present": True,
        "raw_protected_report_tracked": False,
        "additional_host_software_install_required": False,
        "registry_push_performed": False,
        "production_resources_contacted": False,
        "production_deployment_approved": False,
        "full_gate_registered": True,
        "next_requirement": "S144",
        "parallel_requirements_ready": ["S144", "S145", "S146", "S147"],
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s143_production_configuration_secret_tls_closure(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["decision"]["external_staging_acceptance_passed"] is False
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["decision"]["parallel_requirements_ready"] == []
    assert result["failed_checks"]


def test_helpers_cover_evidence_configuration_and_noncanonical_root(
    tmp_path: Path,
) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}
    assert closure._compose_contract(tmp_path) == {}

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
            "passed_audit_count": 7,
            "audit_count": 7,
            "secret_reference_count": 16,
            "compose_service_count": 9,
            "protected_database_count": 5,
            "protected_provider_count": 3,
            "managed_route_count": 9,
        },
        "decision": {"next_requirement": "S144"},
    }
    assert closure.summary_line(passing) == (
        "s143_production_configuration_secret_tls_closure=pass audits=7/7 "
        "secrets=16 compose=9 databases=5 providers=3 routes=9 next=S144"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s143_production_configuration_secret_tls_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s143_production_configuration_secret_tls_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S144" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s143_production_configuration_secret_tls_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
