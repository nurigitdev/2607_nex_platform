from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nex_runtime.calibration_deferred_live_matrix import (
    CalibrationDeferredLiveMatrixError,
    build_calibration_deferred_live_matrix_contract,
    evaluate_calibration_deferred_live_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def _design() -> dict:
    return json.loads(
        (
            ROOT
            / "scripts/smoke/data/gb2_s20r_calibration_closure_deferred_live_matrix_v1_design.json"
        ).read_text(encoding="utf-8")
    )


def _s20q() -> dict:
    return {
        "status": "PASS",
        "decision": "MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED",
        "closure_hash": _design()["s20q_closure_hash"],
        "selected_policy_hash": "sha256:" + "1" * 64,
        "holdout_accessed": False,
        "holdout_reexecution_permitted": False,
    }


def _s20ra() -> dict:
    return {
        "status": "PASS",
        "decision": "DEFERRED_LIVE_RUNNERS_RECONCILED",
        "contract_hash": _design()["s20ra_contract_hash"],
        "selected_policy_hash": "sha256:" + "1" * 64,
        "provider_binding": _design()["provider_binding"],
        "holdout_accessed": False,
        "holdout_reexecuted": False,
    }


def _contract() -> dict:
    return build_calibration_deferred_live_matrix_contract(
        design=_design(),
        s20q_closure=_s20q(),
        s20ra_reconciliation=_s20ra(),
        s20q_document_hash="sha256:" + "2" * 64,
        s20ra_document_hash="sha256:" + "3" * 64,
    )


def _s140() -> dict:
    return {
        "status": "PASS",
        "actual_protected_execution": True,
        "summary": {
            "actual_protected_gate_count": 5,
            "privacy_violation_count": 0,
        },
    }


def _s147() -> dict:
    return {
        "status": "PASS",
        "summary": {
            "live_provider_count": 3,
            "live_model_match_count": 3,
            "runtime_ready_count": 3,
            "generation_reasoning_mode": "disabled",
        },
        "cleanup": {"residue": 0},
    }


def _s149() -> dict:
    generation = _design()["provider_binding"]["generation"]
    return {
        "status": "PASS",
        "executed": True,
        "actual_postgres": True,
        "actual_compose": True,
        "actual_openbao": True,
        "actual_rustfs": True,
        "actual_remote_generation": True,
        "actual_playwright": True,
        "continuity_checks": {"journey": True, "queue_state_stable": True},
        "extended_acceptance": {
            "provider_model_ref": generation["model"],
            "provider_model_revision": generation["revision"],
            "provider_deployment_id": generation["deployment_id"],
        },
    }


def _s150() -> dict:
    return {
        "status": "PASS",
        "executed": True,
        "actual_postgres": True,
        "execution_checks": {
            "component_acceptance_passed": True,
            "actual_postgres": True,
            "scenario_matrix_passed": True,
            "zero_residue": True,
        },
        "cleanup_remaining": 0,
    }


def test_contract_freezes_closed_holdout_and_exact_provider_binding() -> None:
    contract = _contract()

    assert contract["decision"] == "CALIBRATION_ADMITTED"
    assert contract["stage_order"] == ["S136", "S137", "S140", "S147", "S149", "S150"]
    assert contract["provider_binding"]["generation"]["model"] == "Qwen3.5-9B"
    assert contract["holdout_reexecution_permitted"] is False
    assert contract["contract_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [
        ("design", "stage_order", ["S136"]),
        ("s20q", "status", "FAIL"),
        ("s20q", "closure_hash", "sha256:" + "0" * 64),
        ("s20q", "holdout_accessed", True),
        ("s20ra", "status", "FAIL"),
        ("s20ra", "contract_hash", "sha256:" + "0" * 64),
        ("s20ra", "holdout_reexecuted", True),
    ],
)
def test_contract_rejects_lineage_and_holdout_drift(
    source: str, field: str, value: object
) -> None:
    values = {"design": _design(), "s20q": _s20q(), "s20ra": _s20ra()}
    values[source][field] = value

    with pytest.raises(CalibrationDeferredLiveMatrixError):
        build_calibration_deferred_live_matrix_contract(
            design=values["design"],
            s20q_closure=values["s20q"],
            s20ra_reconciliation=values["s20ra"],
            s20q_document_hash="sha256:" + "2" * 64,
            s20ra_document_hash="sha256:" + "3" * 64,
        )


def test_contract_rejects_unknown_design_schema() -> None:
    design = _design()
    design["schema_version"] = "unknown"
    with pytest.raises(CalibrationDeferredLiveMatrixError):
        build_calibration_deferred_live_matrix_contract(
            design=design,
            s20q_closure=_s20q(),
            s20ra_reconciliation=_s20ra(),
            s20q_document_hash="sha256:" + "2" * 64,
            s20ra_document_hash="sha256:" + "3" * 64,
        )


def test_contract_rejects_policy_and_provider_drift() -> None:
    policy = _s20ra()
    policy["selected_policy_hash"] = "sha256:" + "9" * 64
    with pytest.raises(CalibrationDeferredLiveMatrixError):
        build_calibration_deferred_live_matrix_contract(
            design=_design(),
            s20q_closure=_s20q(),
            s20ra_reconciliation=policy,
            s20q_document_hash="sha256:" + "2" * 64,
            s20ra_document_hash="sha256:" + "3" * 64,
        )

    provider = _s20ra()
    provider["provider_binding"] = {}
    with pytest.raises(CalibrationDeferredLiveMatrixError):
        build_calibration_deferred_live_matrix_contract(
            design=_design(),
            s20q_closure=_s20q(),
            s20ra_reconciliation=provider,
            s20q_document_hash="sha256:" + "2" * 64,
            s20ra_document_hash="sha256:" + "3" * 64,
        )


def test_evaluator_accepts_current_semantic_matrix_and_zero_residue() -> None:
    evidence = evaluate_calibration_deferred_live_matrix(
        contract=_contract(),
        s140=_s140(),
        s147=_s147(),
        s149=_s149(),
        s150=_s150(),
    )

    assert evidence["status"] == "PASS"
    assert evidence["decision"] == "CALIBRATION_CLOSED_DEFERRED_MATRIX_PASSED"
    assert all(evidence["checks"].values())
    assert evidence["database_cleanup"] == {
        "s147_residue": 0,
        "s149_queue_state_stable": True,
        "s150_residue": 0,
    }
    assert evidence["next_boundary"] == "REPOSITORY_FULL_GATE"


def test_evaluator_fails_closed_for_each_stage_and_identity_drift() -> None:
    cases = []
    bad_s140 = copy.deepcopy(_s140())
    bad_s140["summary"]["privacy_violation_count"] = 1
    cases.append((bad_s140, _s147(), _s149(), _s150(), "s140_privacy_clean"))
    bad_s147 = copy.deepcopy(_s147())
    bad_s147["cleanup"]["residue"] = 1
    cases.append((_s140(), bad_s147, _s149(), _s150(), "s147_zero_residue"))
    bad_s149 = copy.deepcopy(_s149())
    bad_s149["extended_acceptance"]["provider_model_revision"] = "mutable"
    cases.append((_s140(), _s147(), bad_s149, _s150(), "s149_generation_identity_exact"))
    bad_s150 = copy.deepcopy(_s150())
    bad_s150["cleanup_remaining"] = 1
    cases.append((_s140(), _s147(), _s149(), bad_s150, "s150_zero_residue"))

    for s140, s147, s149, s150, failed in cases:
        evidence = evaluate_calibration_deferred_live_matrix(
            contract=_contract(), s140=s140, s147=s147, s149=s149, s150=s150
        )
        assert evidence["status"] == "FAIL"
        assert failed in evidence["failed_checks"]


def test_evaluator_rejects_invalid_contract() -> None:
    with pytest.raises(CalibrationDeferredLiveMatrixError):
        evaluate_calibration_deferred_live_matrix(
            contract={}, s140=_s140(), s147=_s147(), s149=_s149(), s150=_s150()
        )
