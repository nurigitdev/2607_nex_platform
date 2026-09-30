from __future__ import annotations

from pathlib import Path

from nex_mo.provider_resilience_boundary import (
    RESILIENCE_BOUNDARIES,
    RESILIENCE_POLICY,
    ResilienceBoundary,
    build_mo_provider_resilience_boundary,
)
import run_mo_provider_resilience_boundary as runner


def test_repository_provider_resilience_boundary_is_frozen() -> None:
    result = build_mo_provider_resilience_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == "provider_request_bounded_retry_and_resilience"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 6,
        "capability_count": 3,
        "retryable_failure_kind_count": 4,
        "forbidden_projection_count": 6,
        "evidence_issue_count": 0,
    }
    assert result["next_slice"] == "1143"


def test_boundary_fails_closed_for_missing_source_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (ResilienceBoundary("missing", "missing.py", "token", "9999"),)

    result = build_mo_provider_resilience_boundary(tmp_path, boundaries=boundaries)

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "resilience_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_boundary_inventory_and_policy_are_stable() -> None:
    assert len(RESILIENCE_BOUNDARIES) == 6
    assert RESILIENCE_POLICY["attempt_limits"] == {
        "embedding": 3,
        "reranking": 3,
        "generation": 2,
    }
    assert RESILIENCE_POLICY["persistence"] == "process_local_no_table_in_s115"
    assert RESILIENCE_POLICY["durable_telemetry_requirement"] == "S116"
    assert RESILIENCE_POLICY["gpu_runtime_observability_requirement"] == "S117"


def test_boundary_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_resilience_boundary()
    assert "resilience_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(runner, "run_mo_provider_resilience_boundary", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "boundaries=6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_resilience_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
