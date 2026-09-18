from __future__ import annotations

from pathlib import Path

import pytest

import run_ag_ack_expiry_automation_boundary_audit as audit


def test_ack_expiry_automation_boundary_passes_repo() -> None:
    evidence = audit.run_ag_ack_expiry_automation_boundary_audit()

    assert evidence["status"] == "PASS"
    assert evidence["requirement"] == "S83"
    assert evidence["boundary"] == {
        "boundary": audit.BOUNDARY,
        "owner_service": "nex-ag",
        "source_table": "ag_op_review_ack_state",
        "event_table": "service_operational_events",
        "reconciliation_executor": (
            "run_operator_review_liveness_ack_expiry_reconciliation"
        ),
        "execution_mode": "externally_scheduled_bounded_run_once",
        "new_table_in_slice_0821": False,
        "new_route_in_slice_0821": False,
        "continuous_loop_in_s83": False,
        "subprocess_supervision_in_s83": False,
    }
    assert all(evidence["checks"].values())
    assert evidence["issues"] == []
    assert "boundary=pass" in audit.summary_line(evidence)


def test_ack_expiry_automation_boundary_reports_missing_repo(tmp_path: Path) -> None:
    evidence = audit.run_ag_ack_expiry_automation_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert len(evidence["issues"]) == (
        len(audit.REQUIRED_PATHS) + len(audit.TOKEN_REQUIREMENTS)
    )


def test_ack_expiry_automation_boundary_reports_missing_token(
    tmp_path: Path,
) -> None:
    for item in audit.REQUIRED_PATHS:
        path = tmp_path / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = audit.run_ag_ack_expiry_automation_boundary_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["s82_closed"] is False
    assert evidence["checks"]["bounded_worker_reused"] is False


def test_ack_expiry_automation_boundary_table_length_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "EVENT_TABLE",
        "service_operational_event_history_table_name_too_long",
    )

    evidence = audit.run_ag_ack_expiry_automation_boundary_audit()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(
        item["category"] == "table_name_too_long" for item in evidence["issues"]
    )


def test_ack_expiry_automation_boundary_helpers(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert audit._read_text(missing) == ""
    assert audit._group_present([], "missing") is False
    assert audit.summary_line({"status": "FAIL"}).endswith("next=None")


def test_ack_expiry_automation_boundary_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_ack_expiry_automation_boundary_audit",
        lambda: {"status": "PASS", "boundary": {}, "slice_plan": []},
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_ack_expiry_automation_boundary_audit",
        lambda: {"status": "FAIL", "boundary": {}, "slice_plan": []},
    )
    assert audit.main(["--summary"]) == 1
    assert "boundary=fail" in capsys.readouterr().out


def test_ack_expiry_automation_boundary_quality_gate_wiring() -> None:
    quality_gate = (
        audit.ROOT / "scripts" / "quality" / "run_quality_gate.sh"
    ).read_text(encoding="utf-8")

    assert "run_ag_ack_expiry_automation_boundary_audit.py --summary" in quality_gate
