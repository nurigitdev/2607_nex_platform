from __future__ import annotations

import json
from pathlib import Path

import run_ae_web_grounded_generation_boundary_audit as audit


def test_repository_boundary_audit_passes() -> None:
    result = audit.run_ae_web_grounded_generation_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "foundation_count": 6,
        "gap_count": 8,
        "open_gap_count": 7,
        "resolved_gap_count": 1,
        "drift_count": 3,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["next_slice"] == "1084"


def test_boundary_decision_freezes_browser_and_service_ownership() -> None:
    decision = audit.boundary_decision()

    assert decision["experience_owner"] == "nex-ae-web"
    assert decision["orchestration_owner"] == "nex-ae-api"
    assert decision["grounded_generation_owner"] == "nex-cx"
    assert decision["provider_execution_owner"] == "nex-mo"
    assert decision["browser_service_boundary"] == "same_origin_nex_ae_api_only"
    assert decision["browser_direct_cx_call_allowed"] is False
    assert decision["browser_direct_mo_call_allowed"] is False
    assert decision["browser_service_token_allowed"] is False
    assert decision["new_tables_expected"] == 0
    assert decision["quality_cadence"] == {
        "slice_gate": "every_slice",
        "checkpoint_gate": "1086",
        "full_gate": "1091",
    }


def test_boundary_audit_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_ae_web_grounded_generation_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] == len(audit.REQUIRED_PATHS) + len(
        audit.EVIDENCE_TOKENS
    )
    assert result["summary"]["drift_count"] == 0
    assert result["checks"]["required_paths_present"] is False


def test_boundary_audit_advances_over_resolved_gap_documents(
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
    main_path = tmp_path / "apps/nex-ae-web/src/main.js"
    main_path.write_text(
        main_path.read_text(encoding="utf-8")
        + "\nretrieval 결과와 ${format} handoff를 연결했습니다."
        + "\nbuildMockGroundedResponseQualityContract(true"
        + "\nworkspaceState.progressEvents = buildProgressEvents(grounded)",
        encoding="utf-8",
    )
    for relative_path in tuple(audit.GAP_RESOLUTION_PATHS.values())[:3]:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("resolved\n", encoding="utf-8")

    result = audit.run_ae_web_grounded_generation_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 3
    assert result["summary"]["open_gap_count"] == 5
    assert result["next_slice"] == "1086"


def test_helpers_summary_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._group_present(
        [{"group": "one", "present": False}, {"group": "one", "present": True}],
        "one",
    )
    assert audit._group_present([], "missing") is False

    passing = audit.run_ae_web_grounded_generation_boundary_audit()
    assert audit.summary_line(passing) == (
        "ae_web_grounded_generation_boundary=pass foundations=6 gaps=8 "
        "open=7 drifts=3 issues=0 next=1084"
    )
    assert "next=unknown" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_ae_web_grounded_generation_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_ae_web_grounded_generation_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
