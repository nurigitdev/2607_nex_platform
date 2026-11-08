from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_multi_signal_live_holdout_acceptance_closure_design.v1"
MANIFEST_SCHEMA_VERSION = "cx_multi_signal_live_holdout_acceptance_closure.v1"
DECISION = "MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED"
CLOSURE_STATUS = "CLOSED_PASS"
NEXT_BOUNDARY = "GB2_CA00_S20R_CALIBRATION_CLOSURE_AND_DEFERRED_LIVE_MATRIX_REPLAY"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "closure_contract",
    "acceptance_requirements",
    "scope_evolution",
    "safety",
}
_SOURCE_FIELDS = {
    "retrieval_live_report_document_hash",
    "holdout_report_document_hash",
    "holdout_receipt_document_hash",
    "holdout_receipt_hash",
    "holdout_evaluation_hash",
    "operations_closure_report_document_hash",
    "operations_closure_hash",
    "maintenance_report_document_hash",
    "maintenance_hash",
    "maintenance_policy_hash",
    "selected_policy_hash",
}
_CLOSURE_CONTRACT = {
    "decision": DECISION,
    "closure_status": CLOSURE_STATUS,
    "corrective_chain_closed": True,
    "holdout_reexecution_permitted": False,
    "threshold_or_profile_reselection_permitted": False,
    "next_boundary": NEXT_BOUNDARY,
}
_ACCEPTANCE_REQUIREMENTS = {
    "permission_filtered_hybrid_package_required": True,
    "frozen_policy_untouched_holdout_required": True,
    "immutable_profile_and_runtime_bindings_required": True,
    "actual_cx_postgresql_required": True,
    "actual_remote_embedding_required": True,
    "actual_remote_reranking_required": True,
    "one_shot_authorization_consumed_required": True,
    "steady_state_and_maintenance_closure_required": True,
}
_SCOPE_EVOLUTION = {
    "original_scope": ("PERMISSION_FILTERED_HYBRID_RETRIEVAL_EMBEDDING_AND_RERANKING"),
    "admitted_extension": ("PROVIDER_BACKED_ANSWER_SUPPORT_AND_CONTRADICTION_SIGNAL"),
    "change_control": (
        "SEPARATE_CALIBRATION_ONE_SHOT_HOLDOUT_AND_STAGED_RUNTIME_ADOPTION"
    ),
    "backward_retrieval_contract_preserved": True,
}
_SAFETY = {
    "provider_call_permitted": False,
    "database_call_permitted": False,
    "holdout_access_permitted": False,
    "runtime_mutation_permitted": False,
    "production_cutover_permitted": False,
}
_RETRIEVAL_REPORT_FIELDS = {
    "calibration_admission",
    "checks",
    "database_identity",
    "dataset",
    "evidence_schema_version",
    "failed_checks",
    "holdout_status",
    "migration",
    "nested_selection_status",
    "ordering_policy",
    "pipeline_repeatability",
    "provider_binding",
    "provider_observation",
    "provider_request_counts",
    "slice_id",
    "status",
}
_HOLDOUT_REPORT_FIELDS = {
    "authorization_hash",
    "checks",
    "collection",
    "decision",
    "evaluation",
    "evidence_schema_version",
    "execution_id",
    "failed_checks",
    "provider_evaluation_count",
    "provider_http_request_counts",
    "receipt",
    "runtime_activation_permitted",
    "slice_id",
    "status",
}
_RECEIPT_FIELDS = {
    "attempt_number",
    "authorization_hash",
    "completed_at",
    "dataset_file_sha256",
    "dataset_semantic_sha256",
    "evaluation_hash",
    "execution_id",
    "freeze_hash",
    "provider_evaluation_count",
    "provider_http_request_count",
    "receipt_hash",
    "receipt_schema_version",
    "started_at",
    "status",
    "terminal_reason",
}
_OPERATIONS_REPORT_FIELDS = {
    "automatic_reopen_permitted",
    "baseline_status",
    "checks",
    "closure_hash",
    "closure_status",
    "continuation_policy_hash",
    "corrective_chain_closed",
    "database_calls",
    "decision",
    "design_hash",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "manifest_schema_version",
    "next_boundary",
    "observed_metrics",
    "operations_profile_hash",
    "operator_decision_hash",
    "operator_review_design_hash",
    "operator_review_manifest_hash",
    "operator_review_receipt_document_hash",
    "operator_review_receipt_hash",
    "operator_review_report_document_hash",
    "prior_continuation_receipt_hash",
    "production_cutover_permitted",
    "provider_calls",
    "reopen_triggers",
    "rollback_contract_preserved",
    "runtime_changed",
    "runtime_disposition",
    "selected_policy_hash",
    "slice_id",
    "source_continuation_evidence_hash",
    "source_continuation_report_document_hash",
    "status",
}
_MAINTENANCE_REPORT_FIELDS = {
    "admission_status",
    "automatic_reopen_permitted",
    "baseline_status",
    "checks",
    "continuation_policy_hash",
    "corrective_chain_closed",
    "current_identity",
    "database_calls",
    "decision",
    "drifted_fields",
    "evaluated_at",
    "evidence_schema_version",
    "failed_checks",
    "holdout_accessed",
    "last_reviewed_at",
    "maintenance_hash",
    "maintenance_schema_version",
    "maintenance_status",
    "new_corrective_chain_opened",
    "next_boundary",
    "next_review_due_at",
    "observed_reopen_events",
    "operations_profile_hash",
    "policy_hash",
    "production_cutover_permitted",
    "provider_calls",
    "review_due",
    "rollback_contract_preserved",
    "runtime_changed",
    "runtime_disposition",
    "selected_policy_hash",
    "slice_id",
    "source_closure_design_hash",
    "source_closure_hash",
    "source_closure_report_document_hash",
    "status",
    "triggered_reopen_conditions",
}


class MultiSignalHoldoutAcceptanceClosureError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_multisignal_holdout_acceptance_closure_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN_CLOSURE"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        name: _hash_ref(source.get(name), name) for name in _SOURCE_FIELDS
    }
    if dict(_mapping(design.get("closure_contract"), "closure_contract")) != (
        _CLOSURE_CONTRACT
    ):
        raise _invalid("closure_contract")
    if (
        dict(_mapping(design.get("acceptance_requirements"), "acceptance_requirements"))
        != _ACCEPTANCE_REQUIREMENTS
    ):
        raise _invalid("acceptance_requirements")
    if dict(_mapping(design.get("scope_evolution"), "scope_evolution")) != (
        _SCOPE_EVOLUTION
    ):
        raise _invalid("scope_evolution")
    if dict(_mapping(design.get("safety"), "safety")) != _SAFETY:
        raise _invalid("safety")
    calculated = semantic_sha256_hash_ref(design)
    if (
        supplied_hash is not None
        and _hash_ref(supplied_hash, "design_hash") != calculated
    ):
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_multisignal_holdout_acceptance_closure(
    *,
    design: Mapping[str, Any],
    retrieval_live_report: Mapping[str, Any],
    holdout_report: Mapping[str, Any],
    holdout_receipt: Mapping[str, Any],
    operations_closure_report: Mapping[str, Any],
    maintenance_report: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = validate_multisignal_holdout_acceptance_closure_design(design)
    retrieval = _validate_retrieval_live_report(normalized, retrieval_live_report)
    holdout = _validate_holdout_sources(normalized, holdout_report, holdout_receipt)
    operations = _validate_operations_closure(normalized, operations_closure_report)
    maintenance = _validate_maintenance(normalized, maintenance_report)
    checks = {
        "retrieval_live_report_integrity_verified": True,
        "actual_cx_test_database_verified": True,
        "permission_filtered_hybrid_pipeline_verified": True,
        "embedding_provider_revision_and_calls_verified": True,
        "reranker_provider_revision_and_calls_verified": True,
        "tokenizer_chunk_and_ranking_bindings_verified": True,
        "retrieval_pipeline_repeatability_verified": True,
        "holdout_report_integrity_verified": True,
        "holdout_receipt_integrity_verified": True,
        "holdout_report_receipt_cross_binding_verified": True,
        "untouched_holdout_partition_verified": True,
        "fixed_profile_and_threshold_verified": True,
        "holdout_point_constraints_verified": True,
        "one_shot_authorization_consumed": True,
        "holdout_reexecution_prohibited": True,
        "scope_evolution_recorded": True,
        "operations_closure_integrity_verified": True,
        "corrective_chain_closed": True,
        "maintenance_baseline_integrity_verified": True,
        "maintenance_active_without_drift": True,
        "no_external_calls_in_closure": True,
        "runtime_unchanged": True,
    }
    manifest: dict[str, Any] = {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "decision": DECISION,
        "closure_status": CLOSURE_STATUS,
        "design_hash": normalized["design_hash"],
        **normalized["source_binding"],
        "retrieval_binding": retrieval["binding"],
        "retrieval_execution": retrieval["execution"],
        "holdout_binding": holdout["binding"],
        "holdout_metrics": holdout["metrics"],
        "operations_state": operations,
        "maintenance_state": maintenance,
        "scope_evolution": dict(normalized["scope_evolution"]),
        "checks": checks,
        "failed_checks": [],
        "provider_calls": 0,
        "database_calls": 0,
        "holdout_accessed": False,
        "holdout_reexecution_permitted": False,
        "threshold_or_profile_reselection_permitted": False,
        "runtime_changed": False,
        "corrective_chain_closed": True,
        "production_cutover_permitted": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    manifest["closure_hash"] = semantic_sha256_hash_ref(manifest)
    return manifest


def _validate_retrieval_live_report(
    design: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _RETRIEVAL_REPORT_FIELDS, "retrieval_live_report"))
    source = design["source_binding"]
    if (
        semantic_sha256_hash_ref(report)
        != source["retrieval_live_report_document_hash"]
    ):
        raise _integrity("retrieval_live_report")
    checks = _mapping(report.get("checks"), "retrieval_checks")
    database = _mapping(report.get("database_identity"), "database_identity")
    migration = _mapping(report.get("migration"), "migration")
    dataset = _mapping(report.get("dataset"), "retrieval_dataset")
    pipeline = _mapping(report.get("pipeline_repeatability"), "pipeline_repeatability")
    provider_binding = _mapping(report.get("provider_binding"), "provider_binding")
    observations = _mapping(report.get("provider_observation"), "provider_observation")
    embedding = _mapping(observations.get("embedding"), "embedding_observation")
    reranking = _mapping(observations.get("reranking"), "reranking_observation")
    counts = _mapping(report.get("provider_request_counts"), "provider_request_counts")
    if (
        report.get("evidence_schema_version")
        != "gb2_s20qpa_vector_near_tie_ordering.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-A"
        or report.get("status") != "PASS"
        or report.get("failed_checks") != []
        or not checks
        or any(item is not True for item in checks.values())
        or database != {"database": "nex_cx_test", "role": "nex_cx_user"}
        or migration != {"applied_count": 0, "planned_count": 23, "skipped_count": 23}
        or dataset.get("partition") != "CALIBRATION"
        or dataset.get("scenario_count") != 80
        or dataset.get("package_count") != 160
        or dataset.get("candidate_count") != 640
        or dataset.get("holdout_status") != "SEALED_NOT_COLLECTED"
        or report.get("holdout_status") != "SEALED_NOT_OPENED"
        or pipeline.get("status") != "STABLE"
        or pipeline.get("holdout_access_permitted") is not False
        or pipeline.get("runtime_activation_permitted") is not False
        or counts
        != {"embedding": 1440, "holdout_blocked": 0, "reranking": 800, "total": 2240}
        or embedding.get("success_count") != 1440
        or embedding.get("failure_count") != 0
        or reranking.get("success_count") != 800
        or reranking.get("failure_count") != 0
        or provider_binding.get("embedding_model_revision")
        != "hf:5cf2132abc99cad020ac570b19d031efec650f2b"
        or provider_binding.get("reranker_model_revision")
        != "hf:22e683669bc0f0bd69640a1354a6d0aebcfeede5"
        or provider_binding.get("chunk_policy_id") != "chunk_1000_100"
        or provider_binding.get("ranking_policy_id") != "weighted_rrf_vector_bm25_v1"
        or provider_binding.get("tokenizer_policy_id")
        != "cx-tokenizer-profile:sha256:bea6a191e61ec9c45e5cafc3c973bfcca5fa1147872800b6bb27eb0cab03d7ab"
    ):
        raise _invalid("retrieval_live_boundary")
    return {
        "binding": dict(provider_binding),
        "execution": {
            "database": database["database"],
            "role": database["role"],
            "dataset_id": dataset["dataset_id"],
            "dataset_sha256": dataset["dataset_sha256"],
            "scenario_count": dataset["scenario_count"],
            "package_count": dataset["package_count"],
            "candidate_count": dataset["candidate_count"],
            "embedding_calls": counts["embedding"],
            "reranking_calls": counts["reranking"],
            "provider_failures": 0,
            "cleanup_complete": True,
        },
    }


def _validate_holdout_sources(
    design: Mapping[str, Any],
    report_value: Mapping[str, Any],
    receipt_value: Mapping[str, Any],
) -> dict[str, Any]:
    report = dict(_exact(report_value, _HOLDOUT_REPORT_FIELDS, "holdout_report"))
    receipt = dict(_exact(receipt_value, _RECEIPT_FIELDS, "holdout_receipt"))
    source = design["source_binding"]
    if (
        semantic_sha256_hash_ref(report) != source["holdout_report_document_hash"]
        or semantic_sha256_hash_ref(receipt) != source["holdout_receipt_document_hash"]
    ):
        raise _integrity("holdout_sources")
    receipt_payload = dict(receipt)
    receipt_hash = _hash_ref(receipt_payload.pop("receipt_hash"), "receipt_hash")
    if (
        semantic_sha256_hash_ref(receipt_payload) != receipt_hash
        or receipt_hash != source["holdout_receipt_hash"]
        or report.get("receipt") != receipt
    ):
        raise _integrity("holdout_receipt")
    checks = _mapping(report.get("checks"), "holdout_checks")
    collection = _mapping(report.get("collection"), "holdout_collection")
    collection_dataset = _mapping(collection.get("dataset"), "collection_dataset")
    collection_privacy = _mapping(collection.get("privacy"), "collection_privacy")
    collection_safety = _mapping(collection.get("safety"), "collection_safety")
    provider = _mapping(collection.get("provider_binding"), "holdout_provider")
    evaluation = _mapping(report.get("evaluation"), "holdout_evaluation")
    evaluation_dataset = _mapping(evaluation.get("dataset"), "evaluation_dataset")
    candidate = _mapping(evaluation.get("candidate"), "holdout_candidate")
    metrics = _mapping(evaluation.get("metrics"), "holdout_metrics")
    evaluation_checks = _mapping(evaluation.get("checks"), "evaluation_checks")
    if (
        report.get("evidence_schema_version") != "gb2_s20qpq_one_shot_holdout.v1"
        or report.get("slice_id") != "GB2-CA00-S20Q-P-Q"
        or report.get("status") != "PASS"
        or report.get("decision")
        != "HOLDOUT_EXECUTED_CANDIDATE_ADMITTED_SEPARATE_ACTIVATION_REQUIRED"
        or report.get("failed_checks") != []
        or not checks
        or any(item is not True for item in checks.values())
        or report.get("provider_evaluation_count") != 40
        or report.get("provider_http_request_counts") != {"generation": 40, "total": 40}
        or report.get("runtime_activation_permitted") is not False
        or receipt.get("status") != "PASS"
        or receipt.get("attempt_number") != 1
        or receipt.get("terminal_reason") is not None
        or receipt.get("provider_evaluation_count") != 40
        or receipt.get("provider_http_request_count") != 40
        or receipt.get("evaluation_hash") != source["holdout_evaluation_hash"]
        or collection.get("status") != "HOLDOUT_COLLECTED"
        or collection_dataset.get("partition") != "HOLDOUT"
        or collection_dataset.get("package_count") != 40
        or collection_dataset.get("candidate_count") != 160
        or any(item is not False for item in collection_privacy.values())
        or collection_safety
        != {
            "profile_selection_permitted": False,
            "runtime_activation_permitted": False,
            "threshold_selection_permitted": False,
        }
        or evaluation.get("status") != "HOLDOUT_ADMITTED"
        or evaluation.get("terminal_status") != "PASS"
        or evaluation.get("evaluation_hash") != source["holdout_evaluation_hash"]
        or not evaluation_checks
        or any(item is not True for item in evaluation_checks.values())
        or evaluation_dataset.get("partition") != "HOLDOUT"
        or evaluation_dataset.get("dataset_sha256")
        != receipt.get("dataset_semantic_sha256")
        or candidate.get("profile_id") != "answer-support-contradiction-aware-v2"
        or candidate.get("profile_hash")
        != "sha256:495bbc63c50affddd70e90c97fc27655c94c5eeabf890a5f13f5c2df5f90a31e"
        or candidate.get("threshold") != 0.46375
        or metrics.get("false_ready_rate") != 0.05
        or metrics.get("ready_recall") != 1.0
        or evaluation.get("package_auc") != 1.0
        or provider.get("model_revision")
        != "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    ):
        raise _invalid("holdout_boundary")
    return {
        "binding": {
            "dataset_id": evaluation_dataset["dataset_id"],
            "dataset_semantic_sha256": evaluation_dataset["dataset_sha256"],
            "profile_id": candidate["profile_id"],
            "profile_hash": candidate["profile_hash"],
            "threshold": candidate["threshold"],
            "generation_model_revision": provider["model_revision"],
            "request_profile_id": provider["request_profile_id"],
            "request_profile_hash": collection["request_profile_hash"],
            "score_semantics_id": provider["score_semantics_id"],
            "receipt_hash": receipt_hash,
            "evaluation_hash": evaluation["evaluation_hash"],
        },
        "metrics": {
            "scenario_count": 20,
            "package_count": evaluation_dataset["package_count"],
            "candidate_count": evaluation_dataset["candidate_count"],
            "false_ready_rate": metrics["false_ready_rate"],
            "ready_recall": metrics["ready_recall"],
            "balanced_accuracy": metrics["balanced_accuracy"],
            "package_auc": evaluation["package_auc"],
            "provider_evaluations": report["provider_evaluation_count"],
            "provider_http_requests": report["provider_http_request_counts"]["total"],
            "authorization_consumed": True,
        },
    }


def _validate_operations_closure(
    design: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _OPERATIONS_REPORT_FIELDS, "operations_closure"))
    source = design["source_binding"]
    if (
        semantic_sha256_hash_ref(report)
        != source["operations_closure_report_document_hash"]
    ):
        raise _integrity("operations_closure")
    closure_payload = dict(report)
    closure_payload.pop("evidence_schema_version")
    closure_payload.pop("slice_id")
    closure_hash = _hash_ref(closure_payload.pop("closure_hash"), "closure_hash")
    checks = _mapping(report.get("checks"), "operations_checks")
    if (
        semantic_sha256_hash_ref(closure_payload) != closure_hash
        or closure_hash != source["operations_closure_hash"]
    ):
        raise _integrity("operations_closure_manifest")
    if (
        report.get("status") != "PASS"
        or report.get("decision")
        != "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION_CLOSED"
        or report.get("closure_status") != "CLOSED_CONTROLLED_OPERATIONS_BASELINE"
        or report.get("baseline_status") != "FROZEN"
        or report.get("corrective_chain_closed") is not True
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or report.get("failed_checks") != []
        or not checks
        or any(item is not True for item in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("runtime_changed") is not False
        or report.get("rollback_contract_preserved") is not True
        or report.get("production_cutover_permitted") is not False
    ):
        raise _invalid("operations_closure_boundary")
    return {
        "closure_status": report["closure_status"],
        "baseline_status": report["baseline_status"],
        "runtime_disposition": report["runtime_disposition"],
        "corrective_chain_closed": True,
    }


def _validate_maintenance(
    design: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    report = dict(_exact(value, _MAINTENANCE_REPORT_FIELDS, "maintenance_report"))
    source = design["source_binding"]
    if semantic_sha256_hash_ref(report) != source["maintenance_report_document_hash"]:
        raise _integrity("maintenance_report")
    maintenance_payload = dict(report)
    maintenance_payload.pop("evidence_schema_version")
    maintenance_payload.pop("slice_id")
    maintenance_hash = _hash_ref(
        maintenance_payload.pop("maintenance_hash"), "maintenance_hash"
    )
    checks = _mapping(report.get("checks"), "maintenance_checks")
    if (
        semantic_sha256_hash_ref(maintenance_payload) != maintenance_hash
        or maintenance_hash != source["maintenance_hash"]
        or report.get("policy_hash") != source["maintenance_policy_hash"]
    ):
        raise _integrity("maintenance_manifest")
    if (
        report.get("status") != "PASS"
        or report.get("maintenance_status") != "ACTIVE_CONTROLLED_BASELINE_MAINTENANCE"
        or report.get("admission_status") != "ADMITTED_CONTROLLED_BASELINE"
        or report.get("baseline_status") != "FROZEN"
        or report.get("selected_policy_hash") != source["selected_policy_hash"]
        or report.get("review_due") is not False
        or report.get("drifted_fields") != []
        or report.get("triggered_reopen_conditions") != []
        or report.get("corrective_chain_closed") is not True
        or report.get("new_corrective_chain_opened") is not False
        or report.get("failed_checks") != []
        or not checks
        or any(item is not True for item in checks.values())
        or report.get("provider_calls") != 0
        or report.get("database_calls") != 0
        or report.get("holdout_accessed") is not False
        or report.get("runtime_changed") is not False
        or report.get("production_cutover_permitted") is not False
    ):
        raise _invalid("maintenance_boundary")
    return {
        "maintenance_status": report["maintenance_status"],
        "admission_status": report["admission_status"],
        "review_due": False,
        "drift_detected": False,
        "next_review_due_at": report["next_review_due_at"],
    }


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hash_ref(value: object, name: str) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(name) from exc


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    normalized = _mapping(value, name)
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _invalid(name: str) -> MultiSignalHoldoutAcceptanceClosureError:
    return MultiSignalHoldoutAcceptanceClosureError(
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INVALID", f"{name} is invalid"
    )


def _integrity(name: str) -> MultiSignalHoldoutAcceptanceClosureError:
    return MultiSignalHoldoutAcceptanceClosureError(
        "MULTI_SIGNAL_HOLDOUT_ACCEPTANCE_CLOSURE_INTEGRITY",
        f"{name} integrity failed",
    )
