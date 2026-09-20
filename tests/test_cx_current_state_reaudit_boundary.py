from __future__ import annotations

from pathlib import Path

import run_cx_current_state_reaudit_boundary as audit


def test_boundary_audit_passes_for_repository() -> None:
    result = audit.run_cx_current_state_reaudit_boundary()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"] == {
        "owner": "nex-cx",
        "audit_scope": "cx_fr_001_through_008",
        "repository_state_is_primary_evidence": True,
        "legacy_gap_documents_are_advisory": True,
        "refactor_before_feature_when_needed": True,
        "actual_test_database_evidence_required": True,
        "live_provider_evidence_is_supplementary": True,
        "new_table_required": False,
        "existing_cx_records_mutated": False,
        "next_requirement": "S92",
        "decision_status": "FROZEN",
    }
    assert len(result["audit_surfaces"]) == 8
    assert len(result["slice_plan"]) == 10


def test_boundary_audit_reports_missing_paths_and_tokens(tmp_path: Path) -> None:
    quality = tmp_path / "scripts/quality/run_quality_gate.sh"
    quality.parent.mkdir(parents=True)
    quality.write_text(
        "run_cx_current_state_reaudit_boundary.py\n",
        encoding="utf-8",
    )

    result = audit.run_cx_current_state_reaudit_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert result["checks"]["s90_handoff_ready"] is False
    assert result["checks"]["cx_runtime_reusable"] is False
    assert result["checks"]["audit_inputs_reusable"] is False
    assert any(item["category"] == "path_missing" for item in result["issues"])
    assert any(
        item["category"] == "source_token_missing" for item in result["issues"]
    )


def test_helpers_cover_present_missing_and_groups(tmp_path: Path) -> None:
    present = tmp_path / "present.txt"
    present.write_text("content", encoding="utf-8")
    items = [
        {"group": "ready", "present": True},
        {"group": "blocked", "present": False},
    ]

    assert audit._read_text(present) == "content"
    assert audit._read_text(tmp_path / "missing.txt") == ""
    assert audit._group_present(items, "ready") is True
    assert audit._group_present(items, "blocked") is False
    assert audit._group_present(items, "missing") is False


def test_summary_line_reports_pass_and_failure() -> None:
    passed = audit.summary_line(
        {
            "status": "PASS",
            "decision": {
                "audit_scope": "cx_fr_001_through_008",
                "owner": "nex-cx",
                "new_table_required": False,
                "next_requirement": "S92",
            },
        }
    )
    failed = audit.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    )

    assert "boundary=pass" in passed
    assert "scope=cx_fr_001_through_008" in passed
    assert "owner=nex-cx" in passed
    assert "new_table=False" in passed
    assert "next=S92" in passed
    assert "boundary=fail" in failed
    assert "issues=1" in failed


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "audit_scope": "cx_fr_001_through_008",
            "owner": "nex-cx",
            "new_table_required": False,
            "next_requirement": "S92",
        },
    }
    monkeypatch.setattr(
        audit,
        "run_cx_current_state_reaudit_boundary",
        lambda: passing,
    )

    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_cx_current_state_reaudit_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
