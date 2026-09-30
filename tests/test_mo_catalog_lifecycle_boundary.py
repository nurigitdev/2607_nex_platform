from __future__ import annotations

from pathlib import Path

from nex_mo.catalog_lifecycle_boundary import (
    CATALOG_LIFECYCLE_BOUNDARIES,
    CATALOG_LIFECYCLE_POLICY,
    CatalogLifecycleBoundary,
    build_mo_catalog_lifecycle_boundary,
)
import run_mo_catalog_lifecycle_boundary as runner


def test_repository_catalog_lifecycle_boundary_is_frozen() -> None:
    result = build_mo_catalog_lifecycle_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == (
        "durable_model_catalog_and_atomic_alias_lifecycle"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "boundary_count": 6,
        "required_capability_count": 3,
        "table_count": 2,
        "forbidden_persistence_count": 6,
        "evidence_issue_count": 0,
    }
    assert result["next_slice"] == "1173"


def test_boundary_fails_closed_for_missing_evidence_and_invalid_inventory(
    tmp_path: Path,
) -> None:
    boundaries = (
        CatalogLifecycleBoundary(
            "missing",
            "missing.py",
            "token",
            "REPLACE",
            "9999",
        ),
    )

    result = build_mo_catalog_lifecycle_boundary(
        tmp_path,
        boundaries=boundaries,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["boundary_inventory_complete"] is False
    assert result["checks"]["source_evidence_present"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "catalog_lifecycle_boundary_evidence_missing",
            "boundary_id": "missing",
            "source_path": "missing.py",
        }
    ]


def test_policy_keeps_runtime_secrets_outside_durable_catalog() -> None:
    assert len(CATALOG_LIFECYCLE_BOUNDARIES) == 6
    assert CATALOG_LIFECYCLE_POLICY["tables"] == [
        "mo_model_catalog",
        "mo_alias_bindings",
    ]
    assert CATALOG_LIFECYCLE_POLICY["bootstrap"] == (
        "static_routes_seed_empty_store_only"
    )
    assert "provider_api_key" in CATALOG_LIFECYCLE_POLICY[
        "forbidden_persistence"
    ]
    assert "runtime_profile" in CATALOG_LIFECYCLE_POLICY["allowed_persistence"]


def test_boundary_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_boundary()
    assert "mo_catalog_lifecycle_boundary=pass" in runner.summary_line(passing)

    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_boundary",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "tables=2" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
