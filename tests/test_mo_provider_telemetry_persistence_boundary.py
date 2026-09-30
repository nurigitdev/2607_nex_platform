from __future__ import annotations

from pathlib import Path

from nex_mo.provider_telemetry_persistence_boundary import (
    DURABLE_TELEMETRY_BOUNDARIES,
    DURABLE_TELEMETRY_POLICY,
    DurableTelemetryBoundary,
    build_mo_provider_telemetry_persistence_boundary,
)
import run_mo_provider_telemetry_persistence_boundary as runner


def test_repository_durable_telemetry_boundary_is_frozen() -> None:
    result = build_mo_provider_telemetry_persistence_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == "restart_safe_durable_provider_telemetry"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 6,
        "logical_key_field_count": 4,
        "forbidden_persistence_count": 6,
        "deferred_scope_count": 4,
        "evidence_issue_count": 0,
    }
    assert result["next_slice"] == "1153"


def test_boundary_fails_closed_for_missing_evidence_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (
        DurableTelemetryBoundary("missing", "missing.py", "token", "9999"),
    )

    result = build_mo_provider_telemetry_persistence_boundary(
        tmp_path,
        boundaries=boundaries,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "durable_telemetry_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_durable_telemetry_policy_preserves_privacy_and_wire_shape() -> None:
    assert len(DURABLE_TELEMETRY_BOUNDARIES) == 6
    assert DURABLE_TELEMETRY_POLICY["table_name"] == "mo_provider_telemetry"
    assert DURABLE_TELEMETRY_POLICY["write_semantics"] == "atomic_increment_upsert"
    assert DURABLE_TELEMETRY_POLICY["runtime_modes"] == {
        "memory": "in_memory_store",
        "postgres": "sqlalchemy_durable_store",
    }
    assert "provider_api_key" in DURABLE_TELEMETRY_POLICY["forbidden_persistence"]
    assert "gpu_runtime_metrics" in DURABLE_TELEMETRY_POLICY["deferred_scope"]


def test_boundary_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_telemetry_persistence_boundary()
    assert "persistence_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_persistence_boundary",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "key_fields=4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_telemetry_persistence_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
