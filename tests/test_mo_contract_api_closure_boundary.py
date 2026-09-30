from __future__ import annotations

from nex_mo.contract_api_closure_boundary import (
    CONTRACT_CLOSURE_BOUNDARIES,
    CONTRACT_CLOSURE_POLICY,
    ContractClosureBoundary,
    _count,
    build_mo_contract_api_closure_boundary,
)
import run_mo_contract_api_closure_boundary as runner


def test_repository_contract_api_closure_boundary_is_frozen() -> None:
    result = build_mo_contract_api_closure_boundary()

    assert result["status"] == "PASS"
    assert result["boundary"] == "mo_contract_and_api_drift_closure"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "drift_class_count": 6,
        "baseline_drift_count": 28,
        "target_drift_count": 0,
        "baseline_issue_count": 0,
    }
    assert result["baseline"]["expected"] == result["baseline"]["observed"]
    assert result["next_slice"] == "1133"


def test_contract_closure_policy_preserves_runtime_storage_and_privacy() -> None:
    assert len(CONTRACT_CLOSURE_BOUNDARIES) == 6
    assert CONTRACT_CLOSURE_POLICY["runtime_semantics"] == (
        "preserve_existing_runtime_behavior"
    )
    assert CONTRACT_CLOSURE_POLICY["database_policy"] == (
        "no_new_table_read_write_only_in_protected_smoke"
    )
    assert CONTRACT_CLOSURE_POLICY["provider_policy"] == "no_dgx_call_required"
    assert CONTRACT_CLOSURE_POLICY["checkpoint_slice"] == "1136"
    assert CONTRACT_CLOSURE_POLICY["closure_slice"] == "1141"


def test_boundary_fails_closed_for_baseline_and_inventory_drift() -> None:
    boundaries = (
        ContractClosureBoundary("missing_openapi_operations", 8, "9999", "bad"),
    )
    baseline = {
        "status": "FAIL",
        "summary": {
            "missing_openapi_operation_count": 9,
            "drift_count": 28,
        },
    }

    result = build_mo_contract_api_closure_boundary(
        boundaries=boundaries,
        baseline=baseline,
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["baseline_audit_passed"] is False
    assert result["checks"]["six_drift_classes_frozen"] is False
    assert result["checks"]["baseline_categories_match"] is False
    assert result["checks"]["slice_order_bounded"] is False
    assert result["issues"] == [
        {
            "category": "contract_drift_baseline_mismatch",
            "drift_class": "missing_openapi_operations",
            "expected": 8,
            "observed": 9,
        }
    ]


def test_count_fails_closed_for_invalid_values() -> None:
    assert _count({"value": 3}, "value") == 3
    assert _count({"value": -1}, "value") == 0
    assert _count({"value": "3"}, "value") == 0
    assert _count({}, "value") == 0


def test_boundary_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_contract_api_closure_boundary()
    assert runner.summary_line(passing) == (
        "mo_contract_api_closure_boundary=pass classes=6 "
        "drift=28->0 issues=0 next=1133"
    )

    monkeypatch.setattr(
        runner,
        "run_mo_contract_api_closure_boundary",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "drift=28->0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_contract_api_closure_boundary",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
