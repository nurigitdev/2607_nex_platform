from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

DESIGN_SCHEMA_VERSION = "cx_deferred_live_runner_reconciliation_design.v1"
CONTRACT_SCHEMA_VERSION = "cx_deferred_live_runner_reconciliation_contract.v1"
EVIDENCE_SCHEMA_VERSION = "cx_deferred_live_runner_reconciliation_evidence.v1"
DECISION = "DEFERRED_LIVE_RUNNERS_RECONCILED"
NEXT_BOUNDARY = "GB2_CA00_S20R_CALIBRATION_CLOSURE_AND_DEFERRED_LIVE_MATRIX_REPLAY"

_DESIGN_FIELDS = {
    "design_schema_version",
    "design_id",
    "status",
    "source_binding",
    "runner_mapping",
    "provider_binding",
    "safety",
}
_SOURCE_FIELDS = {
    "s20q_closure_document_hash",
    "s20q_closure_hash",
    "selected_policy_hash",
}
_RUNNER_MAPPING = {
    "s136": {
        "historical_runner": "run_s136_permission_hybrid_live_postgres_smoke",
        "replay_runner": "run_gb2_s20qpa_vector_near_tie_ordering",
        "retired_v1_calibration_reexecution_permitted": False,
    },
    "s137": {
        "runner": "run_platform_grounded_generation_artifact_live_postgres_smoke",
        "shared_product_runtime_composition_required": True,
        "answer_support_primary_policy_required": True,
    },
}
_SAFETY = {
    "holdout_access_permitted": False,
    "holdout_reexecution_permitted": False,
    "threshold_or_profile_reselection_permitted": False,
    "database_migration_change_permitted": False,
    "public_api_change_permitted": False,
    "historical_evidence_mutation_permitted": False,
}


class DeferredLiveRunnerReconciliationError(ValueError):
    def __init__(self, error_code: str, detail: str) -> None:
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


def validate_deferred_live_runner_reconciliation_design(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    design = dict(_mapping(value, "design"))
    supplied_hash = design.pop("design_hash", None)
    _exact(design, _DESIGN_FIELDS, "design")
    if (
        design.get("design_schema_version") != DESIGN_SCHEMA_VERSION
        or design.get("status") != "FROZEN"
        or not _text(design.get("design_id"))
    ):
        raise _invalid("design_identity")
    source = _exact(design.get("source_binding"), _SOURCE_FIELDS, "source_binding")
    design["source_binding"] = {
        field: _hash_ref(source.get(field), field) for field in _SOURCE_FIELDS
    }
    if dict(_mapping(design.get("runner_mapping"), "runner_mapping")) != (
        _RUNNER_MAPPING
    ):
        raise _invalid("runner_mapping")
    provider = dict(_mapping(design.get("provider_binding"), "provider_binding"))
    if set(provider) != {"embedding", "reranking", "generation"}:
        raise _invalid("provider_binding")
    for capability, expected_model in (
        ("embedding", "Qwen3-Embedding-4B"),
        ("reranking", "Qwen3-Reranker-4B"),
        ("generation", "Qwen3.5-9B"),
    ):
        binding = dict(_mapping(provider.get(capability), capability))
        expected_fields = {"model", "revision"}
        if capability == "generation":
            expected_fields.add("deployment_id")
        if set(binding) != expected_fields:
            raise _invalid(f"provider_binding.{capability}")
        if binding.get("model") != expected_model:
            raise _invalid(f"provider_binding.{capability}.model")
        if capability == "generation" and (
            binding.get("deployment_id") != "dgx-qwen3-5-9b-9116"
        ):
            raise _invalid("provider_binding.generation.deployment_id")
        binding["revision"] = _hash_ref(
            binding.get("revision"),
            f"provider_binding.{capability}.revision",
            prefix="hf:",
        )
        provider[capability] = binding
    design["provider_binding"] = provider
    if dict(_mapping(design.get("safety"), "safety")) != _SAFETY:
        raise _invalid("safety")
    calculated = semantic_sha256_hash_ref(design)
    if supplied_hash is not None and _hash_ref(
        supplied_hash, "design_hash"
    ) != calculated:
        raise _integrity("design")
    design["design_hash"] = calculated
    return design


def build_deferred_live_runner_reconciliation_contract(
    *,
    design: Mapping[str, Any],
    s20q_closure: Mapping[str, Any],
    s20q_closure_document_hash: str,
) -> dict[str, Any]:
    normalized = validate_deferred_live_runner_reconciliation_design(design)
    source = normalized["source_binding"]
    closure = dict(_mapping(s20q_closure, "s20q_closure"))
    if _hash_ref(
        s20q_closure_document_hash,
        "s20q_closure_document_hash",
    ) != source["s20q_closure_document_hash"]:
        raise _integrity("s20q_closure_document")
    if (
        closure.get("manifest_schema_version")
        != "cx_multi_signal_live_holdout_acceptance_closure.v1"
        or closure.get("status") != "PASS"
        or closure.get("closure_status") != "CLOSED_PASS"
        or closure.get("closure_hash") != source["s20q_closure_hash"]
        or closure.get("selected_policy_hash") != source["selected_policy_hash"]
        or closure.get("holdout_reexecution_permitted") is not False
        or closure.get("threshold_or_profile_reselection_permitted") is not False
        or closure.get("corrective_chain_closed") is not True
    ):
        raise _integrity("s20q_closure")
    contract: dict[str, Any] = {
        "contract_schema_version": CONTRACT_SCHEMA_VERSION,
        "status": "READY",
        "decision": DECISION,
        "design_hash": normalized["design_hash"],
        **source,
        "runner_mapping": normalized["runner_mapping"],
        "provider_binding": normalized["provider_binding"],
        "safety": normalized["safety"],
        "next_boundary": NEXT_BOUNDARY,
    }
    contract["contract_hash"] = semantic_sha256_hash_ref(contract)
    return contract


def evaluate_deferred_live_runner_replay(
    *,
    contract: Mapping[str, Any],
    s136_replay: Mapping[str, Any],
    s137_replay: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = dict(_mapping(contract, "contract"))
    contract_hash = normalized.pop("contract_hash", None)
    if (
        normalized.get("contract_schema_version") != CONTRACT_SCHEMA_VERSION
        or normalized.get("status") != "READY"
        or normalized.get("decision") != DECISION
        or _hash_ref(contract_hash, "contract_hash")
        != semantic_sha256_hash_ref(normalized)
    ):
        raise _integrity("contract")
    provider = _mapping(normalized.get("provider_binding"), "provider_binding")
    s136 = _mapping(s136_replay, "s136_replay")
    s137 = _mapping(s137_replay, "s137_replay")
    s136_checks = _mapping(s136.get("checks"), "s136_checks")
    s136_binding = _mapping(s136.get("provider_binding"), "s136_binding")
    s137_checks = _mapping(s137.get("checks"), "s137_checks")
    answer_support = _mapping(
        s137.get("answer_support_observation"),
        "answer_support_observation",
    )
    s137_providers = _mapping(s137.get("provider_observation"), "provider_observation")
    residue = _mapping(s137.get("post_journey_residue"), "post_journey_residue")
    checks = {
        "s20q_closure_consumed_without_holdout_reexecution": (
            normalized.get("s20q_closure_hash") is not None
            and _mapping(normalized.get("safety"), "safety").get(
                "holdout_reexecution_permitted"
            )
            is False
        ),
        "s136_current_replay_runner_used": (
            s136.get("evidence_schema_version")
            == "gb2_s20qpa_vector_near_tie_ordering.v1"
            and s136.get("slice_id") == "GB2-CA00-S20Q-P-A"
            and s136.get("status") == "PASS"
        ),
        "s136_actual_postgres_and_cleanup_verified": (
            s136.get("database_identity")
            == {"database": "nex_cx_test", "role": "nex_cx_user"}
            and s136_checks.get("cleanup_complete") is True
        ),
        "s136_permission_pipeline_repeatability_verified": all(
            s136_checks.get(name) is True
            for name in (
                "provider_calls_complete",
                "five_run_pipeline_repeatability_stable",
                "vector_rank_repeatable",
                "rrf_score_repeatable",
                "candidate_membership_repeatable",
                "final_rank_repeatable",
                "holdout_remained_sealed",
                "runtime_activation_prohibited",
            )
        ),
        "s136_provider_revisions_exact": all(
            s136_binding.get(evidence_field)
            == _mapping(provider.get(capability), capability).get("revision")
            for capability, evidence_field in (
                ("embedding", "embedding_model_revision"),
                ("reranking", "reranker_model_revision"),
            )
        ),
        "s137_current_product_runtime_used": (
            s137.get("smoke_schema_version")
            == "platform_grounded_generation_artifact_live_postgres_smoke.v1"
            and s137.get("status") == "PASS"
            and s137_checks.get("canonical_answer_support_policy_applied") is True
        ),
        "s137_answer_support_policy_exact": (
            answer_support.get("primary_policy_installed") is True
            and answer_support.get("steady_state_policy_installed") is True
            and answer_support.get("selected_policy_hash")
            == normalized.get("selected_policy_hash")
        ),
        "qwen35_9b_generation_verified": (
            _mapping(s137_providers.get("generation"), "generation").get("model")
            == _mapping(provider.get("generation"), "generation").get("revision")
        ),
        "s137_actual_postgres_and_zero_residue_verified": (
            s137.get("actual_postgres") is True
            and bool(residue)
            and all(value == 0 for value in residue.values())
        ),
    }
    evidence: dict[str, Any] = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "decision": DECISION if all(checks.values()) else "RECONCILIATION_FAILED",
        "contract_hash": contract_hash,
        "s136_replay_hash": semantic_sha256_hash_ref(dict(s136)),
        "s137_replay_hash": semantic_sha256_hash_ref(dict(s137)),
        "selected_policy_hash": normalized.get("selected_policy_hash"),
        "provider_binding": provider,
        "replay_order": ["S136", "S137"],
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "holdout_accessed": False,
        "holdout_reexecuted": False,
        "retired_v1_calibration_reexecuted": False,
        "database_migration_changed": False,
        "public_api_changed": False,
        "next_boundary": NEXT_BOUNDARY,
    }
    evidence["evidence_hash"] = semantic_sha256_hash_ref(evidence)
    return evidence


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(name)
    return value


def _exact(value: object, fields: set[str], name: str) -> dict[str, Any]:
    normalized = dict(_mapping(value, name))
    if set(normalized) != fields:
        raise _invalid(name)
    return normalized


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _hash_ref(value: object, name: str, *, prefix: str = "sha256:") -> str:
    try:
        if prefix == "sha256:":
            return validate_hash_ref(value)
        if (
            not isinstance(value, str)
            or re.fullmatch(r"hf:[0-9a-f]{40}", value) is None
        ):
            raise ValueError("invalid provider revision")
        return value
    except ValueError as exc:
        raise _invalid(name) from exc


def _invalid(name: str) -> DeferredLiveRunnerReconciliationError:
    return DeferredLiveRunnerReconciliationError(
        "CX_DEFERRED_LIVE_RUNNER_RECONCILIATION_INVALID",
        f"Invalid deferred live runner reconciliation field: {name}.",
    )


def _integrity(name: str) -> DeferredLiveRunnerReconciliationError:
    return DeferredLiveRunnerReconciliationError(
        "CX_DEFERRED_LIVE_RUNNER_RECONCILIATION_INTEGRITY_INVALID",
        f"Deferred live runner reconciliation integrity failed: {name}.",
    )
