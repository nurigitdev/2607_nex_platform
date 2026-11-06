from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_cx.retrieval_answer_support_policy_controlled_steady_state_baseline_maintenance import (
    DECISION,
    MAINTENANCE_STATUS,
    NEXT_BOUNDARY,
    ControlledSteadyStateBaselineMaintenanceError,
    _mapping,
    _timestamp,
    build_controlled_steady_state_baseline_maintenance,
    validate_controlled_steady_state_baseline_maintenance_policy,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT / "services/nex-cx/nex_cx/data/"
    "answer_support_policy_controlled_steady_state_baseline_maintenance.v1.json"
)
CLOSURE_PATH = (
    ROOT / "reports/live/"
    "gb2_ca00_s20qpas_answer_support_policy_steady_state_operations_"
    "continuation_closure.json"
)


def test_maintenance_admits_exact_frozen_baseline_without_external_calls() -> None:
    result = _build()

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["maintenance_status"] == MAINTENANCE_STATUS
    assert result["admission_status"] == "ADMITTED_CONTROLLED_BASELINE"
    assert result["baseline_status"] == "FROZEN"
    assert result["review_due"] is False
    assert result["drifted_fields"] == []
    assert result["triggered_reopen_conditions"] == []
    assert result["corrective_chain_closed"] is True
    assert result["new_corrective_chain_opened"] is False
    assert result["automatic_reopen_permitted"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_changed"] is False
    assert result["rollback_contract_preserved"] is True
    assert result["production_cutover_permitted"] is False
    assert result["next_boundary"] == NEXT_BOUNDARY
    assert all(result["checks"].values())


def test_committed_policy_is_integrity_bound_and_hash_may_be_calculated() -> None:
    policy = _policy()
    normalized = validate_controlled_steady_state_baseline_maintenance_policy(policy)
    assert normalized["policy_hash"] == policy["policy_hash"]

    without_hash = deepcopy(policy)
    without_hash.pop("policy_hash")
    assert (
        validate_controlled_steady_state_baseline_maintenance_policy(without_hash)[
            "policy_hash"
        ]
        == policy["policy_hash"]
    )

    for path, value in (
        (("status",), "DRAFT"),
        (("policy_schema_version",), "wrong"),
        (("policy_id",), ""),
        (("maintenance_contract", "automatic_reopen_permitted"), True),
        (("safety", "provider_call_permitted"), True),
        (("drift_trigger_map", "selected_policy_hash"), "wrong"),
    ):
        drift = deepcopy(policy)
        target = drift
        for name in path[:-1]:
            target = target[name]
        target[path[-1]] = value
        with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
            validate_controlled_steady_state_baseline_maintenance_policy(drift)

    drift = deepcopy(policy)
    drift["policy_id"] += "-copy"
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError) as raised:
        validate_controlled_steady_state_baseline_maintenance_policy(drift)
    assert raised.value.error_code == (
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INTEGRITY"
    )

    drift = deepcopy(policy)
    drift["reopen_triggers"] = list(reversed(drift["reopen_triggers"]))
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        validate_controlled_steady_state_baseline_maintenance_policy(drift)


def test_closure_document_and_manifest_drift_fail_closed() -> None:
    report = _closure()
    report["observed_metrics"]["elapsed_seconds"] = 1.0
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError) as raised:
        _build(closure_report=report)
    assert raised.value.error_code == (
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INTEGRITY"
    )

    report = _closure()
    report.pop("observed_metrics")
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError) as raised:
        _build(closure_report=report)
    assert raised.value.error_code == (
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INVALID"
    )

    report = _closure()
    report["runtime_changed"] = True
    policy = _policy_for_rehashed_report(report)
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError) as raised:
        build_controlled_steady_state_baseline_maintenance(
            policy=policy,
            closure_report=report,
            last_reviewed_at="2026-11-06T00:00:00Z",
            evaluated_at="2026-11-06T00:00:01Z",
        )
    assert raised.value.error_code == (
        "CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE_INVALID"
    )


@pytest.mark.parametrize(
    ("field", "expected_trigger"),
    [
        ("source_closure_hash", "EXPLICIT_OPERATOR_REOPEN_DECISION"),
        (
            "continuation_policy_hash",
            "CALIBRATION_DATASET_OR_SELECTED_POLICY_CHANGED",
        ),
        ("operations_profile_hash", "OPERATIONS_PROFILE_OR_SLO_CHANGED"),
        (
            "selected_policy_hash",
            "CALIBRATION_DATASET_OR_SELECTED_POLICY_CHANGED",
        ),
    ],
)
def test_identity_drift_requires_explicit_reopen_and_holds_runtime(
    field: str, expected_trigger: str
) -> None:
    identity = deepcopy(_policy()["source_binding"])
    identity[field] = "sha256:" + "0" * 64

    result = _build(current_identity=identity)

    assert result["status"] == "PASS"
    assert result["maintenance_status"] == "BASELINE_REOPEN_REQUIRED"
    assert result["admission_status"] == "FAIL_CLOSED_REOPEN_REQUIRED"
    assert result["drifted_fields"] == [field]
    assert result["triggered_reopen_conditions"] == [expected_trigger]
    assert result["runtime_disposition"] == (
        "HOLD_CONTROLLED_BASELINE_PENDING_EXPLICIT_REOPEN"
    )
    assert result["runtime_changed"] is False
    assert result["new_corrective_chain_opened"] is False


def test_event_driven_reopen_is_deduplicated_but_never_automatic() -> None:
    trigger = "PERMISSION_OR_TENANT_BOUNDARY_CHANGED"
    result = _build(observed_reopen_events=(trigger, trigger))
    assert result["observed_reopen_events"] == [trigger]
    assert result["triggered_reopen_conditions"] == [trigger]
    assert result["automatic_reopen_permitted"] is False
    assert result["new_corrective_chain_opened"] is False

    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _build(observed_reopen_events=("UNKNOWN",))

    malformed_identity = deepcopy(_policy()["source_binding"])
    malformed_identity["selected_policy_hash"] = "bad"
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _build(current_identity=malformed_identity)
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _build(current_identity={})


def test_expired_review_window_holds_baseline_for_operator_review() -> None:
    result = _build(
        last_reviewed_at="2026-11-01T00:00:00Z",
        evaluated_at="2026-12-02T00:00:00Z",
    )
    assert result["review_due"] is True
    assert result["next_review_due_at"] == "2026-12-01T00:00:00Z"
    assert result["maintenance_status"] == "PERIODIC_REVIEW_DUE"
    assert result["admission_status"] == "FAIL_CLOSED_REVIEW_REQUIRED"
    assert result["triggered_reopen_conditions"] == []
    assert result["runtime_disposition"] == (
        "HOLD_CONTROLLED_BASELINE_PENDING_OPERATOR_REVIEW"
    )


@pytest.mark.parametrize(
    ("last_reviewed_at", "evaluated_at"),
    [
        ("bad", "2026-11-06T00:00:00Z"),
        ("2026-11-06T00:00:00", "2026-11-06T00:00:00Z"),
        ("2026-11-07T00:00:00Z", "2026-11-06T00:00:00Z"),
    ],
)
def test_invalid_review_windows_fail_closed(
    last_reviewed_at: str, evaluated_at: str
) -> None:
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _build(last_reviewed_at=last_reviewed_at, evaluated_at=evaluated_at)


def test_mapping_and_timestamp_guards() -> None:
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _mapping([], "mapping")
    with pytest.raises(ControlledSteadyStateBaselineMaintenanceError):
        _timestamp(None, "timestamp")


def _build(
    *,
    closure_report=None,
    current_identity=None,
    observed_reopen_events=(),
    last_reviewed_at: str = "2026-11-06T00:00:00Z",
    evaluated_at: str = "2026-11-06T00:00:01Z",
):
    return build_controlled_steady_state_baseline_maintenance(
        policy=_policy(),
        closure_report=closure_report or _closure(),
        current_identity=current_identity,
        observed_reopen_events=observed_reopen_events,
        last_reviewed_at=last_reviewed_at,
        evaluated_at=evaluated_at,
    )


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _closure() -> dict:
    return json.loads(CLOSURE_PATH.read_text(encoding="utf-8"))


def _policy_for_rehashed_report(report: dict) -> dict:
    closure_payload = deepcopy(report)
    closure_payload.pop("evidence_schema_version")
    closure_payload.pop("slice_id")
    closure_payload.pop("closure_hash")
    report["closure_hash"] = semantic_sha256_hash_ref(closure_payload)

    policy = _policy()
    policy["source_binding"]["source_closure_hash"] = report["closure_hash"]
    policy["source_binding"]["source_closure_report_document_hash"] = (
        semantic_sha256_hash_ref(report)
    )
    policy.pop("policy_hash")
    policy["policy_hash"] = semantic_sha256_hash_ref(policy)
    return policy
