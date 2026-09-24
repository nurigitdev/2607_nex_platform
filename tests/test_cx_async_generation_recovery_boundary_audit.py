from __future__ import annotations

import json
from pathlib import Path

import run_cx_async_generation_recovery_boundary_audit as audit


def test_repository_async_generation_boundary_passes() -> None:
    result = audit.run_cx_async_generation_recovery_boundary_audit()

    assert result["status"] == "PASS"
    assert result["summary"]["foundation_count"] == 7
    assert result["summary"]["gap_count"] == 8
    assert result["summary"]["open_gap_count"] + result["summary"][
        "resolved_gap_count"
    ] == 8
    assert result["summary"]["planned_slice_count"] == 10
    assert result["summary"]["issue_count"] == 0
    assert all(result["checks"].values())
    assert result["next_slice"] in set(audit.GAP_SLICES.values()) | {"0991"}


def test_async_generation_boundary_freezes_runtime_decisions() -> None:
    decision = audit._boundary_decision()

    assert decision["queue_policy"] == (
        "reuse_service_jobs_with_deterministic_idempotent_job"
    )
    assert decision["request_storage_policy"] == (
        "owner_private_immutable_envelope"
    )
    assert decision["new_table_expected"] is False
    assert decision["remote_provider_required_now"] is False
    assert decision["quality_cadence"]["checkpoint_gate"] == "0986"


def test_async_generation_boundary_fails_closed_for_missing_repo(
    tmp_path: Path,
) -> None:
    result = audit.run_cx_async_generation_recovery_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["checks"]["required_paths_present"] is False
    assert result["summary"]["issue_count"] > 0


def test_async_generation_boundary_tracks_resolved_gap(tmp_path: Path) -> None:
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
        "async_execution_contract_missing"
    ]
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text("# resolved\n", encoding="utf-8")

    result = audit.run_cx_async_generation_recovery_boundary_audit(tmp_path)

    assert result["status"] == "PASS"
    assert result["summary"]["resolved_gap_count"] == 1
    assert result["next_slice"] == "0984"


def test_async_generation_boundary_helpers_and_main(monkeypatch, capsys) -> None:
    passing = audit.run_cx_async_generation_recovery_boundary_audit()
    assert audit._group_present([], "missing") is False
    assert audit.summary_line(passing).startswith(
        "cx_async_generation_recovery_boundary=pass foundations=7 gaps=8 "
    )
    assert "scope=cx_asynchronous_grounded_generation_execution_recovery" in (
        audit.summary_line(passing)
    )
    assert "scope=unknown" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_cx_async_generation_recovery_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_async_generation_recovery_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
