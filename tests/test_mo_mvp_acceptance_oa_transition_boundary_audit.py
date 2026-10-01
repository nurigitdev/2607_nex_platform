from __future__ import annotations

import json
from pathlib import Path

import run_mo_mvp_acceptance_oa_transition_boundary_audit as audit


def test_repository_boundary_is_frozen() -> None:
    result = audit.run_mo_mvp_acceptance_oa_transition_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert result["summary"] == {
        "foundation_count": 7,
        "closure_count": 9,
        "gap_count": 8,
        "open_gap_count": 8,
        "resolved_gap_count": 0,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert all(result["checks"].values())
    assert result["next_slice"] == "1193"


def test_boundary_decision_freezes_live_database_and_quality_scope() -> None:
    decision = audit.boundary_decision()

    assert decision["acceptance_scope"] == "nex_mo_service_mvp"
    assert decision["transition_target"] == "nex-oa"
    assert decision["actual_databases_required"] == ["nex_mo_test"]
    assert decision["provider_models"] == [
        "Qwen3-Embedding-4B",
        "Qwen3-Reranker-4B",
        "Qwen3.5-4B",
    ]
    assert decision["new_tables_expected"] == 0
    assert decision["quality_cadence"]["checkpoint_gate"] == "1196"
    assert decision["quality_cadence"]["full_gate"] == "1201"


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_mo_mvp_acceptance_oa_transition_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] > 0
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["s111_s119_closures_present"] is False


def test_resolved_gap_sequence_advances_to_first_open_slice(tmp_path: Path) -> None:
    for relative_path in audit.REQUIRED_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(item.token for item in audit.EVIDENCE_TOKENS), encoding="utf-8")
    for item in audit.EVIDENCE_TOKENS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(f"{existing}\n{item.token}\n", encoding="utf-8")
    for number in range(111, 119):
        runner = tmp_path / "scripts/smoke" / f"run_s{number}_test_closure.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("closure", encoding="utf-8")
        document = tmp_path / "docs/slices" / f"0000_s{number}_closure.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("closure", encoding="utf-8")
    first_gap = tmp_path / audit.GAP_RESOLUTION_PATHS["acceptance_policy_missing"]
    first_gap.parent.mkdir(parents=True, exist_ok=True)
    first_gap.write_text("resolved", encoding="utf-8")

    result = audit.run_mo_mvp_acceptance_oa_transition_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["next_slice"] == "1194"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = audit.run_mo_mvp_acceptance_oa_transition_boundary_audit()
    assert audit.summary_line(passing) == (
        "mo_mvp_acceptance_oa_transition_boundary=pass closures=9 "
        "gaps=8 open=8 issues=0 next=1193"
    )
    failing = {"status": "FAIL", "summary": {}, "next_slice": "1193"}
    assert "boundary=fail" in audit.summary_line(failing)

    monkeypatch.setattr(
        audit,
        "run_mo_mvp_acceptance_oa_transition_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        audit,
        "run_mo_mvp_acceptance_oa_transition_boundary_audit",
        lambda: failing,
    )
    assert audit.main([]) == 1


def test_read_helpers_handle_missing_and_present_files(tmp_path: Path) -> None:
    assert audit._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ready", encoding="utf-8")
    assert audit._read_text(present) == "ready"
    assert audit._group_present(
        [{"group": "ready", "present": True}], "ready"
    )
    assert not audit._group_present([], "missing")
