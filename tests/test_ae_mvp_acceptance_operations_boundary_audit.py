from __future__ import annotations

import json
from pathlib import Path

import run_ae_mvp_acceptance_operations_boundary_audit as audit


def test_repository_boundary_audit_passes() -> None:
    result = audit.run_ae_mvp_acceptance_operations_boundary_audit()
    resolved = sum(
        (audit.ROOT / path).is_file()
        for path in audit.GAP_RESOLUTION_PATHS.values()
    )
    expected_next = next(
        (
            audit.GAP_SLICES[name]
            for name, path in audit.GAP_RESOLUTION_PATHS.items()
            if not (audit.ROOT / path).is_file()
        ),
        "1101",
    )

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "foundation_count": 7,
        "closure_count": 9,
        "gap_count": 8,
        "open_gap_count": 8 - resolved,
        "resolved_gap_count": resolved,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["next_slice"] == expected_next


def test_boundary_decision_is_fail_closed_and_operations_scoped() -> None:
    decision = audit.boundary_decision()

    assert decision["acceptance_scope"] == "nex_ae_service_mvp"
    assert decision["services"] == ["nex-ae-api", "nex-ae-web"]
    assert decision["product_wide_release_approval"] is False
    assert decision["production_deployment_certification"] is False
    assert decision["server_derived_evidence_required"] is True
    assert decision["skipped_required_gate_allowed"] is False
    assert decision["raw_evidence_in_projection"] is False
    assert decision["actual_databases_required"] == ["nex_ae_test", "nex_cx_test"]
    assert decision["new_tables_expected"] == 0
    assert decision["quality_cadence"]["full_gate"] == "1101"


def test_boundary_audit_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_ae_mvp_acceptance_operations_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["closure_count"] == 9
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS) + 9
    )
    assert result["checks"]["s101_s109_closures_present"] is False


def test_boundary_audit_advances_across_resolution_documents(
    tmp_path: Path,
) -> None:
    for relative_path in audit.REQUIRED_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    for token in audit.EVIDENCE_TOKENS:
        path = tmp_path / token.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(f"{existing}\n{token.token}\n", encoding="utf-8")
    for number in range(101, 109):
        runner = tmp_path / f"scripts/smoke/run_s{number}_fixture_closure.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("closure\n", encoding="utf-8")
        document = tmp_path / f"docs/slices/{number}0_s{number}_closure.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("closure\n", encoding="utf-8")
    for relative_path in tuple(audit.GAP_RESOLUTION_PATHS.values())[:3]:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("resolved\n", encoding="utf-8")

    result = audit.run_ae_mvp_acceptance_operations_boundary_audit(tmp_path)

    assert result["status"] == "PASS", result
    assert result["summary"]["resolved_gap_count"] == 3
    assert result["summary"]["open_gap_count"] == 5
    assert result["next_slice"] == "1096"


def test_helpers_summary_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._group_present(
        [{"group": "one", "present": False}, {"group": "one", "present": True}],
        "one",
    )
    assert audit._group_present([], "missing") is False

    passing = audit.run_ae_mvp_acceptance_operations_boundary_audit()
    summary = passing["summary"]
    assert audit.summary_line(passing) == (
        "ae_mvp_acceptance_operations_boundary=pass closures=9 gaps=8 "
        f"open={summary['open_gap_count']} issues=0 next={passing['next_slice']}"
    )
    assert "next=unknown" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_ae_mvp_acceptance_operations_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_ae_mvp_acceptance_operations_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
