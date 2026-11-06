from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .semantic_hashes import semantic_sha256_hash_ref


SCHEMA_VERSION = "calibration_deferred_live_matrix.v1"
EVIDENCE_SCHEMA_VERSION = "calibration_deferred_live_matrix_evidence.v1"
REQUIRED_STAGES = ("S136", "S137", "S140", "S147", "S149", "S150")


class CalibrationDeferredLiveMatrixError(ValueError):
    pass


def build_calibration_deferred_live_matrix_contract(
    *,
    design: Mapping[str, Any],
    s20q_closure: Mapping[str, Any],
    s20ra_reconciliation: Mapping[str, Any],
    s20q_document_hash: str,
    s20ra_document_hash: str,
) -> dict[str, Any]:
    if design.get("schema_version") != SCHEMA_VERSION:
        raise CalibrationDeferredLiveMatrixError("design schema is not admitted")
    if tuple(design.get("stage_order") or ()) != REQUIRED_STAGES:
        raise CalibrationDeferredLiveMatrixError("deferred stage order drift")
    if s20q_closure.get("status") != "PASS" or s20q_closure.get("decision") != (
        "MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED"
    ):
        raise CalibrationDeferredLiveMatrixError("S20Q closure is not admitted")
    if s20q_closure.get("closure_hash") != design.get("s20q_closure_hash"):
        raise CalibrationDeferredLiveMatrixError("S20Q closure hash drift")
    if s20ra_reconciliation.get("status") != "PASS" or s20ra_reconciliation.get(
        "decision"
    ) != "DEFERRED_LIVE_RUNNERS_RECONCILED":
        raise CalibrationDeferredLiveMatrixError("S20R-A reconciliation is not admitted")
    if s20ra_reconciliation.get("contract_hash") != design.get(
        "s20ra_contract_hash"
    ):
        raise CalibrationDeferredLiveMatrixError("S20R-A contract hash drift")
    if s20q_closure.get("selected_policy_hash") != s20ra_reconciliation.get(
        "selected_policy_hash"
    ):
        raise CalibrationDeferredLiveMatrixError("selected policy lineage drift")
    if s20q_closure.get("holdout_accessed") is not False or s20q_closure.get(
        "holdout_reexecution_permitted"
    ) is not False:
        raise CalibrationDeferredLiveMatrixError("HOLDOUT closure is not sealed")
    if s20ra_reconciliation.get("holdout_accessed") is not False or (
        s20ra_reconciliation.get("holdout_reexecuted") is not False
    ):
        raise CalibrationDeferredLiveMatrixError("S20R-A reopened HOLDOUT")
    provider_binding = _mapping(s20ra_reconciliation.get("provider_binding"))
    if provider_binding != design.get("provider_binding"):
        raise CalibrationDeferredLiveMatrixError("provider identity drift")

    contract = {
        "schema_version": SCHEMA_VERSION,
        "decision": "CALIBRATION_ADMITTED",
        "stage_order": list(REQUIRED_STAGES),
        "stage_mapping": design.get("stage_mapping"),
        "provider_binding": provider_binding,
        "selected_policy_hash": s20q_closure.get("selected_policy_hash"),
        "s20q_closure_hash": s20q_closure.get("closure_hash"),
        "s20q_document_hash": s20q_document_hash,
        "s20ra_contract_hash": s20ra_reconciliation.get("contract_hash"),
        "s20ra_document_hash": s20ra_document_hash,
        "holdout_reexecution_permitted": False,
        "threshold_change_permitted": False,
        "profile_reselection_permitted": False,
    }
    contract["contract_hash"] = semantic_sha256_hash_ref(contract)
    return contract


def evaluate_calibration_deferred_live_matrix(
    *,
    contract: Mapping[str, Any],
    s140: Mapping[str, Any],
    s147: Mapping[str, Any],
    s149: Mapping[str, Any],
    s150: Mapping[str, Any],
) -> dict[str, Any]:
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise CalibrationDeferredLiveMatrixError("matrix contract is invalid")

    s140_summary = _mapping(s140.get("summary"))
    s147_summary = _mapping(s147.get("summary"))
    s147_cleanup = _mapping(s147.get("cleanup"))
    s149_checks = _mapping(s149.get("continuity_checks"))
    s149_extended = _mapping(s149.get("extended_acceptance"))
    s150_checks = _mapping(s150.get("execution_checks"))
    provider = _mapping(contract.get("provider_binding"))
    generation = _mapping(provider.get("generation"))

    checks = {
        "calibration_decision_admitted": contract.get("decision")
        == "CALIBRATION_ADMITTED",
        "s136_s137_reconciliation_consumed": contract.get("s20ra_contract_hash")
        is not None,
        "holdout_remained_sealed": contract.get("holdout_reexecution_permitted")
        is False,
        "threshold_and_profile_unchanged": contract.get(
            "threshold_change_permitted"
        )
        is False
        and contract.get("profile_reselection_permitted") is False,
        "s140_protected_matrix_passed": s140.get("status") == "PASS",
        "s140_actual_protected_gates_complete": s140.get(
            "actual_protected_execution"
        )
        is True
        and s140_summary.get("actual_protected_gate_count") == 5,
        "s140_privacy_clean": s140_summary.get("privacy_violation_count") == 0,
        "s147_provider_rollout_passed": s147.get("status") == "PASS",
        "s147_actual_three_provider_capabilities": s147_summary.get(
            "live_provider_count"
        )
        == 3
        and s147_summary.get("live_model_match_count") == 3
        and s147_summary.get("runtime_ready_count") == 3,
        "s147_reasoning_disabled": s147_summary.get("generation_reasoning_mode")
        == "disabled",
        "s147_zero_residue": s147_cleanup.get("residue") == 0,
        "s149_current_installed_journey_passed": s149.get("status") == "PASS"
        and s149.get("executed") is True,
        "s149_current_topology_live": all(
            s149.get(name) is True
            for name in (
                "actual_postgres",
                "actual_compose",
                "actual_openbao",
                "actual_rustfs",
                "actual_remote_generation",
                "actual_playwright",
            )
        ),
        "s149_restart_and_queue_invariants": bool(s149_checks)
        and all(value is True for value in s149_checks.values()),
        "s149_generation_identity_exact": s149_extended.get(
            "provider_model_ref"
        )
        == generation.get("model")
        and s149_extended.get("provider_model_revision")
        == generation.get("revision")
        and s149_extended.get("provider_deployment_id")
        == generation.get("deployment_id"),
        "s150_fail_closed_restart_passed": s150.get("status") == "PASS"
        and s150.get("executed") is True,
        "s150_actual_postgres": s150.get("actual_postgres") is True,
        "s150_failure_matrix_complete": bool(s150_checks)
        and all(value is True for value in s150_checks.values()),
        "s150_zero_residue": s150.get("cleanup_remaining") == 0,
        "matrix_stage_order_exact": tuple(contract.get("stage_order") or ())
        == REQUIRED_STAGES,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    evidence = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "PASS" if not failed_checks else "FAIL",
        "decision": (
            "CALIBRATION_CLOSED_DEFERRED_MATRIX_PASSED"
            if not failed_checks
            else "DEFERRED_LIVE_MATRIX_BLOCKED"
        ),
        "contract_hash": contract.get("contract_hash"),
        "selected_policy_hash": contract.get("selected_policy_hash"),
        "provider_binding": provider,
        "stage_order": list(REQUIRED_STAGES),
        "stage_status": {
            "S136": "PASS_REUSED_FROM_S20R_A",
            "S137": "PASS_REUSED_FROM_S20R_A",
            "S140": s140.get("status"),
            "S147": s147.get("status"),
            "S149": s149.get("status"),
            "S150": s150.get("status"),
        },
        "checks": checks,
        "failed_checks": failed_checks,
        "holdout_accessed": False,
        "holdout_reexecuted": False,
        "database_cleanup": {
            "s147_residue": s147_cleanup.get("residue"),
            "s149_queue_state_stable": s149_checks.get("queue_state_stable"),
            "s150_residue": s150.get("cleanup_remaining"),
        },
        "full_gate_required": True,
        "next_boundary": "REPOSITORY_FULL_GATE" if not failed_checks else "BLOCKED",
    }
    evidence["evidence_hash"] = semantic_sha256_hash_ref(evidence)
    return evidence


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
