from __future__ import annotations

import json
from pathlib import Path

import run_cx_mvp_integration_ae_handoff_boundary_audit as audit


def test_repository_s100_boundary_audit_passes() -> None:
    result = audit.run_cx_mvp_integration_ae_handoff_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_CURRENT"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "foundation_count": 8,
        "gap_count": 8,
        "open_gap_count": 5,
        "resolved_gap_count": 3,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert result["next_slice"] == "0996"


def test_s100_boundary_freezes_storage_provider_and_repair_policy() -> None:
    decision = audit._boundary_decision()

    assert decision["new_table_expected"] is False
    assert decision["remote_provider_required_now"] is False
    assert decision["remote_provider_required_slice"] == "1000"
    assert decision["remote_provider_path"] == "cx_to_mo_capability_alias_only"
    assert decision["citation_repair_policy"] == (
        "one_bounded_repair_attempt_same_retrieval_package"
    )
    assert decision["quality_cadence"] == {
        "slice_gate": "0992-1001",
        "checkpoint_gate": "0996",
        "full_gate": "1001",
    }


def test_s100_boundary_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = audit.run_cx_mvp_integration_ae_handoff_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert not result["checks"]["required_paths_present"]
    assert not result["checks"]["required_tokens_present"]
    assert result["summary"]["issue_count"] == (
        len(audit.REQUIRED_PATHS) + len(audit.EVIDENCE_TOKENS)
    )


def test_s100_boundary_tracks_resolved_gaps(tmp_path: Path) -> None:
    for path in audit.REQUIRED_PATHS:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    for item in audit.EVIDENCE_TOKENS:
        target = tmp_path / item.relative_path
        target.write_text(
            target.read_text(encoding="utf-8") + item.token,
            encoding="utf-8",
        )
    first_gap = next(iter(audit.GAP_RESOLUTION_PATHS.values()))
    target = tmp_path / first_gap
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("ready", encoding="utf-8")

    result = audit.run_cx_mvp_integration_ae_handoff_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["summary"]["open_gap_count"] == 7
    assert result["next_slice"] == "0994"


def test_s100_boundary_helpers_and_main_paths(monkeypatch, capsys) -> None:
    result = audit.run_cx_mvp_integration_ae_handoff_boundary_audit()
    assert audit.summary_line(result) == (
        "cx_mvp_integration_ae_handoff_boundary=pass foundations=8 gaps=8 "
        "open=5 scope=cx_mvp_integration_and_ae_handoff_closure "
        "live_required_slice=1000 issues=0"
    )
    assert audit._read_text(Path("missing-s100-boundary")) == ""

    monkeypatch.setattr(
        audit,
        "run_cx_mvp_integration_ae_handoff_boundary_audit",
        lambda: result,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_mvp_integration_ae_handoff_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
