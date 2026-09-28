from __future__ import annotations

import json
from pathlib import Path

import run_ae_citation_repair_workflow_boundary_audit as audit


def test_repository_boundary_audit_passes() -> None:
    result = audit.run_ae_citation_repair_workflow_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "foundation_count": 8,
        "gap_count": 8,
        "open_gap_count": 1,
        "resolved_gap_count": 7,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["next_slice"] == "1060"
    assert result["issues"] == []


def test_boundary_freezes_owners_repair_modes_and_privacy() -> None:
    decision = audit.boundary_decision()

    assert decision["cx_generation_quality_owner"] == "nex-cx"
    assert decision["ae_workflow_projection_owner"] == "nex-ae-api"
    assert decision["ag_operator_remediation_owner"] == "nex-ag"
    assert decision["repair_modes_must_remain_distinct"] is True
    assert decision["bounded_repair_model"] == (
        "one_inline_attempt_same_retrieval_package"
    )
    assert decision["operator_repair_model"] == (
        "separate_ag_cx_remediation_lineage"
    )
    assert decision["new_tables_expected"] == 0
    assert decision["remote_provider_required"] is False
    assert decision["quality_cadence"]["checkpoint_gate"] == "1056"


def test_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_ae_citation_repair_workflow_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS)
    )


def test_gap_progression_and_helpers(tmp_path: Path) -> None:
    for path in audit.REQUIRED_PATHS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    for item in audit.EVIDENCE_TOKENS:
        target = tmp_path / item.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            (target.read_text(encoding="utf-8") if target.is_file() else "")
            + item.token,
            encoding="utf-8",
        )
    first_gap = next(iter(audit.GAP_RESOLUTION_PATHS.values()))
    target = tmp_path / first_gap
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ready", encoding="utf-8")

    result = audit.run_ae_citation_repair_workflow_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["next_slice"] == "1054"
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._group_present(result["required_tokens"], "cx_bounded_repair")
    assert not audit._group_present(result["required_tokens"], "missing")


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    result = audit.run_ae_citation_repair_workflow_boundary_audit()
    assert "boundary=pass" in audit.summary_line(result)
    assert "gaps=8" in audit.summary_line(result)
    assert "boundary=fail" in audit.summary_line(
        {"status": "FAIL", "issues": [{}]}
    )

    monkeypatch.setattr(
        audit,
        "run_ae_citation_repair_workflow_boundary_audit",
        lambda: result,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_ae_citation_repair_workflow_boundary_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
