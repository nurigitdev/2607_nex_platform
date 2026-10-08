from __future__ import annotations

from pathlib import Path

import run_s145_postgresql_resilience_closure as closure


def test_repository_closure_passes_and_hands_off_to_s146() -> None:
    result = closure.run_s145_postgresql_resilience_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S146"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "audit_check_count": 64,
        "check_count": 15,
        "passed_check_count": 15,
        "gap_count": 8,
        "database_count": 5,
        "wal_segment_count": 6,
        "residue_count": 0,
    }
    assert result["decision"] == {
        "single_host_cold_recovery_accepted": True,
        "high_availability_implemented": False,
        "automatic_failover_implemented": False,
        "operator_cutover_required": True,
        "actual_test_databases_used": True,
        "source_controlled_attestation_present": True,
        "raw_protected_report_tracked": False,
        "production_resources_contacted": False,
        "production_deployment_approved": False,
        "production_sized_recovery_deferred_to_s149": True,
        "full_gate_registered": True,
        "next_requirement": "S146",
        "s148_dependency_ready": True,
        "s149_dependency_ready": True,
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s145_postgresql_resilience_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["decision"]["single_host_cold_recovery_accepted"] is False
    assert result["decision"]["actual_test_databases_used"] is False
    assert result["decision"]["source_controlled_attestation_present"] is False
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["decision"]["s148_dependency_ready"] is False
    assert result["decision"]["s149_dependency_ready"] is False
    assert result["failed_checks"]


def test_helpers_cover_files_evidence_and_noncanonical_root(
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
    assert closure._file_digest(source).startswith("sha256:")
    source.write_text("not-json", encoding="utf-8")
    assert closure._load_json(source) == {}
    assert closure._load_json(tmp_path / "missing.json") == {}
    assert closure._file_digest(tmp_path / "missing.bin") == ""

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
            "database_count": 5,
            "wal_segment_count": 6,
            "residue_count": 0,
        },
        "decision": {"next_requirement": "S146"},
    }
    assert closure.summary_line(passing) == (
        "s145_postgresql_resilience_closure=pass audits=8/8 gaps=8 "
        "databases=5 wal=6 residue=0 next=S146"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s145_postgresql_resilience_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s145_postgresql_resilience_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S146" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s145_postgresql_resilience_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
