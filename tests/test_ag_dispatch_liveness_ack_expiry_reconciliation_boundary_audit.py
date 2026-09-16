from __future__ import annotations

from pathlib import Path
import runpy
import sys

import pytest
import run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit as audit


def test_s82_boundary_audit_passes_repository() -> None:
    evidence = (
        audit.run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit()
    )

    assert evidence["status"] == "PASS"
    assert evidence["slice"] == "0811"
    assert evidence["requirement"] == "S82"
    assert evidence["boundary"] == {
        "boundary": audit.BOUNDARY,
        "owner_service": "nex-ag",
        "source_table": "ag_op_review_ack_state",
        "new_table_in_slice_0811": False,
        "mutation_route_in_slice_0811": False,
        "source_liveness_projection_mutated": False,
        "stored_transition": "SUPPRESSED_TO_EXPIRED",
        "candidate_rule": (
            "state_status_SUPPRESSED_and_suppressed_until_lte_observed_at"
        ),
    }
    assert evidence["decisions"]["compare_and_set_required"] is True
    assert evidence["decisions"]["retention_deferred_to_s89"] is True
    assert evidence["slice_plan"][0] == "Slice_0812_contract_and_transition"
    assert evidence["slice_plan"][-1] == "Slice_0820_closure"
    assert all(evidence["checks"].values())
    assert evidence["issues"] == []


def test_s82_boundary_summary() -> None:
    evidence = (
        audit.run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit()
    )

    assert audit.summary_line(evidence) == (
        "ag_dispatch_liveness_ack_expiry_reconciliation_boundary=pass "
        "table=ag_op_review_ack_state new_table=False "
        "transition=SUPPRESSED_TO_EXPIRED next=Slice_0812_contract_and_transition"
    )


def test_s82_boundary_reports_missing_repository(tmp_path: Path) -> None:
    evidence = (
        audit.run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit(
            tmp_path
        )
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"].endswith("boundary_failed")
    assert evidence["checks"]["required_paths_present"] is False
    assert evidence["checks"]["required_tokens_present"] is False
    assert {item["category"] for item in evidence["issues"]} == {
        "path_missing",
        "source_token_missing",
    }
    assert "boundary=fail" in audit.summary_line(evidence)


def test_s82_boundary_reports_token_failure(tmp_path: Path) -> None:
    for required in audit.REQUIRED_PATHS:
        path = tmp_path / required.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = (
        audit.run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit(
            tmp_path
        )
    )

    assert evidence["checks"]["required_paths_present"] is True
    assert evidence["checks"]["required_tokens_present"] is False
    assert all(
        issue["category"] == "source_token_missing"
        for issue in evidence["issues"]
    )


def test_s82_boundary_reports_long_table_name(monkeypatch) -> None:
    monkeypatch.setattr(audit, "ACK_STATE_TABLE", "x" * 31)

    evidence = (
        audit.run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit()
    )

    assert evidence["checks"]["table_names_within_limit"] is False
    assert any(
        issue["category"] == "table_name_too_long"
        for issue in evidence["issues"]
    )


def test_s82_group_present_requires_members() -> None:
    assert audit._group_present([], "missing") is False
    assert audit._group_present(
        [{"group": "g", "present": True}], "g"
    ) is True
    assert audit._group_present(
        [
            {"group": "g", "present": True},
            {"group": "g", "present": False},
        ],
        "g",
    ) is False


def test_s82_main_summary_and_json(capsys, monkeypatch) -> None:
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out

    assert audit.main([]) == 0
    assert '"audit_schema_version"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_ag_dispatch_liveness_ack_expiry_reconciliation_boundary_audit",
        lambda: {
            "status": "FAIL",
            "boundary": {},
            "slice_plan": [],
        },
    )
    assert audit.main(["--summary"]) == 1
    assert "boundary=fail" in capsys.readouterr().out


def test_s82_read_text_handles_oserror(tmp_path: Path) -> None:
    assert audit._read_text(tmp_path / "missing") == ""


def test_s82_script_entrypoint(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(Path(audit.__file__)), "--summary"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(audit.__file__, run_name="__main__")

    assert exc_info.value.code == 0
    assert "boundary=pass" in capsys.readouterr().out
