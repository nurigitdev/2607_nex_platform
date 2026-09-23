from __future__ import annotations

import json
from pathlib import Path

import run_cx_worker_operations_resilience_boundary_audit as audit


def test_repository_worker_operations_resilience_boundary_passes() -> None:
    result = audit.run_cx_worker_operations_resilience_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_CURRENT"
    assert result["summary"] == {
        "foundation_count": 6,
        "gap_count": 8,
        "open_gap_count": 6,
        "resolved_gap_count": 2,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert all(result["checks"].values())
    assert all(result["gap_checks"].values())
    assert result["gap_states"]["worker_execution_contract_missing"] == (
        "RESOLVED"
    )
    assert result["gap_states"]["durable_claim_lease_controls_missing"] == (
        "RESOLVED"
    )
    assert list(result["gap_states"].values()).count("OPEN") == 6
    assert result["next_slice"] == "0975"


def test_worker_operations_boundary_freezes_runtime_decisions() -> None:
    decision = audit._boundary_decision()

    assert decision["queue_policy"] == (
        "reuse_service_jobs_and_atomic_skip_locked_claim"
    )
    assert decision["worker_process_policy"] == (
        "external_bounded_process_not_queue_controlled"
    )
    assert decision["new_table_expected"] is False
    assert decision["postgres_required_now"] is False
    assert decision["postgres_required_slice"] == "0980"
    assert decision["remote_provider_required_now"] is False
    assert decision["quality_cadence"] == {
        "slice_gate": "0972-0981",
        "checkpoint_gate": "0976",
        "full_gate": "0981",
    }
    assert "asynchronous_grounded_generation_execution" in decision["deferred_scope"]


def test_worker_operations_boundary_fails_closed_for_missing_repo(
    tmp_path: Path,
) -> None:
    result = audit.run_cx_worker_operations_resilience_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] > 0
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False


def test_worker_operations_boundary_tracks_resolved_gap(tmp_path: Path) -> None:
    for relative_path in audit.REQUIRED_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    for token in audit.EVIDENCE_TOKENS:
        path = tmp_path / token.relative_path
        path.write_text(
            path.read_text(encoding="utf-8") + token.token + "\n",
            encoding="utf-8",
        )
    resolved = tmp_path / audit.GAP_RESOLUTION_PATHS[
        "worker_execution_contract_missing"
    ]
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text("# resolved\n", encoding="utf-8")

    result = audit.run_cx_worker_operations_resilience_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["gap_states"]["worker_execution_contract_missing"] == "RESOLVED"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["summary"]["open_gap_count"] == 7
    assert result["next_slice"] == "0974"


def test_worker_operations_boundary_helpers_and_main(monkeypatch, capsys) -> None:
    passing = audit.run_cx_worker_operations_resilience_boundary_audit()
    assert audit._group_present([], "missing") is False
    assert audit.summary_line(passing) == (
        "cx_worker_operations_resilience_boundary=pass foundations=6 gaps=8 "
        "open=6 scope=cx_worker_operations_and_resilience "
        "postgres_required_now=False issues=0"
    )
    assert "scope=unknown" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_cx_worker_operations_resilience_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_worker_operations_resilience_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
