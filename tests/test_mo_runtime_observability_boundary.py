from __future__ import annotations

from pathlib import Path

from nex_mo.runtime_observability_boundary import (
    RUNTIME_OBSERVABILITY_BOUNDARIES,
    RUNTIME_OBSERVABILITY_POLICY,
    RuntimeObservabilityBoundary,
    build_mo_runtime_observability_boundary,
)
import run_mo_runtime_observability_boundary as runner


def test_repository_runtime_observability_boundary_is_frozen() -> None:
    result = build_mo_runtime_observability_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == "gpu_and_model_runtime_observability"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 6,
        "required_capability_count": 3,
        "runtime_status_count": 4,
        "forbidden_projection_count": 7,
        "evidence_issue_count": 0,
    }
    assert result["next_slice"] == "1163"


def test_boundary_fails_closed_for_missing_evidence_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (
        RuntimeObservabilityBoundary("missing", "missing.py", "token", "9999"),
    )

    result = build_mo_runtime_observability_boundary(
        tmp_path,
        boundaries=boundaries,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "runtime_observability_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_runtime_observability_policy_preserves_privacy_and_ownership() -> None:
    assert len(RUNTIME_OBSERVABILITY_BOUNDARIES) == 6
    assert RUNTIME_OBSERVABILITY_POLICY["default_mode"] == "mock"
    assert RUNTIME_OBSERVABILITY_POLICY["persistence"] == (
        "process_local_snapshot_no_table_in_s117"
    )
    assert "process_command_line" in RUNTIME_OBSERVABILITY_POLICY[
        "forbidden_projection"
    ]
    assert "gpu_memory_used_mib" in RUNTIME_OBSERVABILITY_POLICY[
        "allowed_projection"
    ]


def test_boundary_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_observability_boundary()
    assert "runtime_observability_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_boundary",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "capabilities=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_runtime_observability_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
