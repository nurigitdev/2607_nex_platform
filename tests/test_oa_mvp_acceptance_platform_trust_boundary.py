from __future__ import annotations

import json
from pathlib import Path

import run_oa_mvp_acceptance_platform_trust_boundary as audit


def test_repository_boundary_is_frozen() -> None:
    result = audit.run_oa_mvp_acceptance_platform_trust_boundary()
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
        "1301",
    )

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert result["summary"] == {
        "requirement_count": 5,
        "closure_count": 9,
        "gap_count": 8,
        "open_gap_count": 8 - resolved,
        "resolved_gap_count": resolved,
        "consumer_count": 4,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert all(result["checks"].values())
    assert result["next_slice"] == expected_next


def test_boundary_decision_freezes_acceptance_and_quality_scope() -> None:
    decision = audit.boundary_decision()

    assert decision["acceptance_scope"] == (
        "oa_fr_001_through_005_platform_trust"
    )
    assert decision["actual_database"] == "nex_oa_test"
    assert decision["actual_role"] == "nex_oa_user"
    assert decision["cross_service_consumers"] == (
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ag",
    )
    assert decision["cross_service_profile"] == "SIGNED_ONLY"
    assert decision["database_private_key_material_allowed"] is False
    assert decision["remote_model_provider_required"] is False
    assert decision["new_tables_expected"] == 0
    assert decision["quality_cadence"] == {
        "slice_gate": "1292-1300",
        "checkpoint_gate": "1296",
        "full_gate": "1301",
    }


def test_boundary_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_oa_mvp_acceptance_platform_trust_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] > 0
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["s121_s129_closures_present"] is False


def test_resolved_gap_sequence_advances_to_first_open_slice(
    tmp_path: Path,
) -> None:
    for relative_path in audit.REQUIRED_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ready", encoding="utf-8")
    for item in audit.EVIDENCE_TOKENS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(f"{existing}\n{item.token}\n", encoding="utf-8")
    for number in range(121, 129):
        runner = tmp_path / "scripts/smoke" / f"run_s{number}_test_closure.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("closure", encoding="utf-8")
        document = tmp_path / "docs/slices" / f"0000_s{number}_closure.md"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("closure", encoding="utf-8")
    first_gap = tmp_path / audit.GAP_RESOLUTION_PATHS[
        "signed_token_failure_audit_missing"
    ]
    first_gap.parent.mkdir(parents=True, exist_ok=True)
    first_gap.write_text("resolved", encoding="utf-8")

    result = audit.run_oa_mvp_acceptance_platform_trust_boundary(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["next_slice"] == "1294"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = audit.run_oa_mvp_acceptance_platform_trust_boundary()
    summary = passing["summary"]
    assert audit.summary_line(passing) == (
        "oa_mvp_acceptance_platform_trust_boundary=pass requirements=5 "
        f"closures=9 gaps=8 open={summary['open_gap_count']} issues=0 "
        f"next={passing['next_slice']}"
    )
    failing = {"status": "FAIL", "summary": {}, "next_slice": "1293"}
    assert "boundary=fail" in audit.summary_line(failing)

    monkeypatch.setattr(
        audit,
        "run_oa_mvp_acceptance_platform_trust_boundary",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        audit,
        "run_oa_mvp_acceptance_platform_trust_boundary",
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
