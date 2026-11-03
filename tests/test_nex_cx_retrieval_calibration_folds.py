from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import nex_cx.retrieval_calibration_folds as fold_module
import pytest
from nex_cx.retrieval_calibration_folds import (
    NestedFoldAssignmentError,
    _assign_stratified_groups,
    _calibration_scenarios,
    _rebalance_marginals,
    _require_exact_partition,
    build_retrieval_calibration_nested_fold_plan,
)
from test_nex_runtime_model_calibration_package_dataset_v4 import build_v4_dataset

ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "scripts"
    / "smoke"
    / "data"
    / "s136_retrieval_package_calibration_v4_design.json"
)


def _design() -> dict:
    return json.loads(DESIGN_PATH.read_text(encoding="utf-8"))


def test_builds_deterministic_nested_group_fold_plan() -> None:
    dataset = build_v4_dataset()
    plan = build_retrieval_calibration_nested_fold_plan(dataset, _design())

    assert plan["status"] == "ASSIGNED"
    assert plan["dataset"]["calibration_scenario_count"] == 80
    assert plan["dataset"]["holdout_scenario_count"] == 20
    assert plan["holdout_access_permitted"] is False
    assert plan["runtime_activation_permitted"] is False
    outer = plan["assignment"]["outer_folds"]
    assert len(outer) == 5
    assert {fold["validation_scenario_count"] for fold in outer} == {16}
    assert {fold["training_scenario_count"] for fold in outer} == {64}
    outer_ids = [
        scenario_id for fold in outer for scenario_id in fold["validation_scenario_ids"]
    ]
    assert len(outer_ids) == len(set(outer_ids)) == 80
    assert not any(int(value.rsplit("-", 1)[1]) > 80 for value in outer_ids)
    for fold in outer:
        assert len(fold["inner_folds"]) == 4
        inner_ids = [
            scenario_id
            for inner in fold["inner_folds"]
            for scenario_id in inner["validation_scenario_ids"]
        ]
        assert len(inner_ids) == len(set(inner_ids)) == 64
        assert not set(inner_ids) & set(fold["validation_scenario_ids"])
        assert {inner["validation_scenario_count"] for inner in fold["inner_folds"]} == {16}
        assert {inner["training_scenario_count"] for inner in fold["inner_folds"]} == {48}
    serialized = json.dumps(plan)
    assert "package query" not in serialized
    assert "candidate text" not in serialized
    assert plan["fold_plan_hash"].startswith("sha256:")

    reordered = build_v4_dataset()
    reordered["cases"].reverse()  # type: ignore[union-attr]
    reordered["scenario_reviews"].reverse()  # type: ignore[union-attr]
    replay = build_retrieval_calibration_nested_fold_plan(reordered, _design())
    assert replay == plan


def test_fold_plan_preserves_reasonable_domain_and_language_balance() -> None:
    plan = build_retrieval_calibration_nested_fold_plan(
        build_v4_dataset(), _design()
    )
    outer = plan["assignment"]["outer_folds"]
    for field in ("domain", "language_profile"):
        labels = {
            label
            for fold in outer
            for label in fold["validation_strata"][field]
        }
        for label in labels:
            counts = [fold["validation_strata"][field].get(label, 0) for fold in outer]
            assert max(counts) - min(counts) <= 1


def test_rejects_invalid_dataset_before_assignment() -> None:
    dataset = build_v4_dataset()
    dataset["scenario_reviews"].pop()  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="scenario_reviews"):
        build_retrieval_calibration_nested_fold_plan(dataset, _design())


def test_defensive_fold_helpers_fail_closed() -> None:
    rows = [
        {"scenario_id": "scenario-001", "domain": "A", "language_profile": "K"},
        {"scenario_id": "scenario-002", "domain": "A", "language_profile": "K"},
    ]
    with pytest.raises(NestedFoldAssignmentError, match="fold geometry"):
        _assign_stratified_groups(
            rows,
            fold_count=2,
            target_size=2,
            seed="seed",
            namespace="outer",
        )
    with pytest.raises(NestedFoldAssignmentError, match="partition"):
        _require_exact_partition([[rows[0], rows[0]]], expected={"scenario-001"}, field="outer")

    _rebalance_marginals(
        [[rows[0]], [rows[1]]], seed="seed", namespace="already-balanced"
    )

    incomplete_cases = [
        case
        for case in build_v4_dataset()["cases"]  # type: ignore[index]
        if case["scenario_id"] != "scenario-001"  # type: ignore[index]
    ]
    with pytest.raises(NestedFoldAssignmentError, match="calibration scenario count"):
        _calibration_scenarios(incomplete_cases)


def test_design_drift_is_rejected() -> None:
    design = deepcopy(_design())
    design["selection_protocol"]["assignment_seed"] = "other"
    with pytest.raises(ValueError, match="assignment_seed"):
        build_retrieval_calibration_nested_fold_plan(build_v4_dataset(), design)


def test_dataset_design_binding_mismatch_is_rejected(monkeypatch) -> None:
    dataset = {
        "dataset_schema_version": "model_calibration_dataset.v4",
        "dataset_id": "dataset-a",
    }
    design = {
        "dataset": {
            "target_schema_version": "model_calibration_dataset.v4",
            "target_dataset_id": "dataset-b",
        }
    }
    monkeypatch.setattr(
        fold_module,
        "admit_model_calibration_package_dataset_v4",
        lambda _payload: SimpleNamespace(dataset=dataset),
    )
    monkeypatch.setattr(
        fold_module,
        "admit_retrieval_calibration_v4_design",
        lambda _payload: SimpleNamespace(design=design),
    )

    with pytest.raises(NestedFoldAssignmentError, match="binding mismatch"):
        build_retrieval_calibration_nested_fold_plan({}, {})
