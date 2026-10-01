from __future__ import annotations

from pathlib import Path

from nex_mo.operations_integration_boundary import (
    OPERATIONS_INTEGRATION_BOUNDARIES,
    OPERATIONS_INTEGRATION_POLICY,
    OperationsIntegrationBoundary,
    build_mo_operations_integration_boundary,
)
import run_mo_operations_integration_boundary as runner


def test_repository_operations_integration_boundary_is_frozen() -> None:
    result = build_mo_operations_integration_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == (
        "mo_operations_integration_and_protected_live_acceptance"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 8,
        "source_count": 4,
        "required_capability_count": 3,
        "new_table_count": 0,
        "evidence_issue_count": 0,
    }
    assert result["next_slice"] == "1183"


def test_boundary_fails_closed_for_missing_evidence_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (
        OperationsIntegrationBoundary(
            "missing",
            "missing.py",
            "token",
            "COMPOSE",
            "9999",
        ),
    )

    result = build_mo_operations_integration_boundary(
        tmp_path,
        boundaries=boundaries,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["next_slice"] == "blocked"
    assert result["issues"] == [
        {
            "category": "operations_integration_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_policy_reuses_persistence_and_requires_protected_acceptance() -> None:
    assert len(OPERATIONS_INTEGRATION_BOUNDARIES) == 8
    assert OPERATIONS_INTEGRATION_POLICY["new_tables"] == []
    assert OPERATIONS_INTEGRATION_POLICY["status_precedence"][0] == (
        "UNAVAILABLE"
    )
    assert OPERATIONS_INTEGRATION_POLICY["acceptance_database"] == (
        "nex_mo_user@nex_mo_test"
    )
    assert "provider_api_key" in OPERATIONS_INTEGRATION_POLICY[
        "forbidden_projection"
    ]


def test_boundary_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_operations_integration_boundary()
    assert "mo_operations_integration_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_operations_integration_boundary",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "new_tables=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_operations_integration_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
