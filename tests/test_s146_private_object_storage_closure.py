from __future__ import annotations

from pathlib import Path

import run_s146_private_object_storage_closure as closure


def test_repository_closure_passes_and_hands_off_to_s147() -> None:
    result = closure.run_s146_private_object_storage_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S147"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "compose": "PASS",
    }
    assert result["summary"] == {
        "audit_count": 2,
        "passed_audit_count": 2,
        "audit_check_count": 21,
        "check_count": 16,
        "passed_check_count": 16,
        "database_count": 5,
        "bucket_count": 2,
        "migration_owner_count": 2,
        "restored_object_count": 1,
        "residue_count": 0,
    }
    assert result["decision"] == {
        "single_host_rustfs_accepted": True,
        "s3_application_boundary_accepted": True,
        "actual_test_databases_used": True,
        "source_controlled_attestation_present": True,
        "raw_protected_report_tracked": False,
        "high_availability_implemented": False,
        "independent_object_backup_proven": False,
        "production_resources_contacted": False,
        "production_deployment_approved": False,
        "full_gate_registered": True,
        "next_requirement": "S147",
        "s148_object_storage_input_ready": True,
        "s149_object_storage_input_ready": True,
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s146_private_object_storage_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "s146_private_object_storage_closure_failed"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["summary"]["residue_count"] == 0
    assert result["failed_checks"]
    assert result["decision"]["single_host_rustfs_accepted"] is False
    assert result["decision"]["s3_application_boundary_accepted"] is False
    assert result["decision"]["actual_test_databases_used"] is False
    assert result["decision"]["source_controlled_attestation_present"] is False
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["decision"]["s148_object_storage_input_ready"] is False
    assert result["decision"]["s149_object_storage_input_ready"] is False


def test_helpers_cover_files_digests_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    assert closure._read_text(source) == '{"ok": true}'
    assert closure._read_text(tmp_path / "missing.md") == ""
    assert closure._load_json(source) == {"ok": True}
    assert closure._file_digest(source).startswith("sha256:")

    source.write_text("[]", encoding="utf-8")
    assert closure._load_json(source) == {}
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


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_audit_count": 2,
            "audit_count": 2,
            "database_count": 5,
            "bucket_count": 2,
            "migration_owner_count": 2,
            "restored_object_count": 1,
            "residue_count": 0,
        },
        "decision": {"next_requirement": "S147"},
    }
    assert closure.summary_line(passing) == (
        "s146_private_object_storage_closure=pass audits=2/2 databases=5 "
        "buckets=2 migrations=2 restores=1 residue=0 next=S147"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s146_private_object_storage_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s146_private_object_storage_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S147" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s146_private_object_storage_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
