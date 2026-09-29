from __future__ import annotations

from pathlib import Path

from nex_mo.provider_readiness_boundary import (
    READINESS_BOUNDARIES,
    READINESS_POLICY,
    ReadinessBoundary,
    build_mo_provider_readiness_boundary,
)
import run_mo_provider_readiness_boundary as runner


def test_repository_provider_readiness_boundary_is_frozen() -> None:
    result = build_mo_provider_readiness_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == "provider_aware_readiness_and_route_health"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 6,
        "required_capability_count": 3,
        "route_health_status_count": 4,
        "forbidden_projection_count": 6,
        "evidence_issue_count": 0,
    }
    assert result["readiness_policy"]["persistence"] == (
        "process_local_no_table_in_s113"
    )
    assert result["next_slice"] == "1123"


def test_boundary_fails_closed_for_missing_source_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (
        ReadinessBoundary("missing", "missing.py", "token", "9999"),
    )

    result = build_mo_provider_readiness_boundary(tmp_path, boundaries=boundaries)

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "readiness_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_boundary_inventory_and_policy_are_stable() -> None:
    assert len(READINESS_BOUNDARIES) == 6
    assert READINESS_POLICY["default_ttl_seconds"] == 30
    assert READINESS_POLICY["refresh_policy"] == "bounded_on_demand_ttl_cache"
    assert READINESS_POLICY["mock_mode"] == "deterministic_ready_without_network"


def test_boundary_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_readiness_boundary()
    assert "readiness_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_readiness_boundary", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "boundaries=6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_readiness_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
