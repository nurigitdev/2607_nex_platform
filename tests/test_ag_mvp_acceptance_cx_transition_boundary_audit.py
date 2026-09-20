from __future__ import annotations

from pathlib import Path

import run_ag_mvp_acceptance_cx_transition_boundary_audit as audit


def test_boundary_audit_passes_for_repository() -> None:
    result = audit.run_ag_mvp_acceptance_cx_transition_boundary_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"] == {
        "owner": "nex-ag",
        "acceptance_scope": "nex_ag_service_mvp",
        "product_wide_release_approval": False,
        "evidence_is_server_derived": True,
        "actual_test_database_evidence_required": True,
        "full_regression_and_branch_coverage_required": True,
        "new_table_required": False,
        "existing_ag_records_mutated": False,
        "cx_transition_requires_all_blocking_gates_pass": True,
        "transition_target": "nex-cx",
        "decision_status": "FROZEN",
    }
    assert len(result["blocking_gate_families"]) == 7
    assert len(result["slice_plan"]) == 10


def test_boundary_audit_reports_missing_paths_and_tokens(tmp_path: Path) -> None:
    quality_path = tmp_path / "scripts/quality/run_quality_gate.sh"
    quality_path.parent.mkdir(parents=True)
    quality_path.write_text(
        "run_ag_mvp_acceptance_cx_transition_boundary_audit.py\n",
        encoding="utf-8",
    )

    result = audit.run_ag_mvp_acceptance_cx_transition_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False
    assert result["checks"]["s89_closed"] is False
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
                "acceptance_scope": "nex_ag_service_mvp",
                "transition_target": "nex-cx",
                "new_table_required": False,
            },
        }
    )
    failed = audit.summary_line(
        {"status": "FAIL", "issues": [{"category": "missing"}]}
    )

    assert "boundary=pass" in passed
    assert "scope=nex_ag_service_mvp" in passed
    assert "target=nex-cx" in passed
    assert "new_table=False" in passed
    assert "boundary=fail" in failed
    assert "issues=1" in failed


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "decision": {
            "acceptance_scope": "nex_ag_service_mvp",
            "transition_target": "nex-cx",
            "new_table_required": False,
        },
    }
    monkeypatch.setattr(
        audit,
        "run_ag_mvp_acceptance_cx_transition_boundary_audit",
        lambda: passing,
    )

    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_mvp_acceptance_cx_transition_boundary_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
