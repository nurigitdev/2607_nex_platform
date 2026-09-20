from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
AG_CX_TRANSITION_HANDOFF_SCHEMA_VERSION = "ag_cx_transition_handoff.v1"
AG_CX_TRANSITION_ATTESTATION_SCHEMA_VERSION = (
    "ag_cx_transition_handoff_attestation.v1"
)
AG_MVP_ACCEPTANCE_POLICY_ID = "ag-mvp-acceptance-v1"

REQUIRED_CONTRACT_PATHS = (
    "contracts/schemas/service/nex_cx/upload_registration.v1.schema.json",
    "contracts/schemas/service/nex_cx/source_ownership_boundary_decision.v1.schema.json",
    "contracts/schemas/service/nex_cx/text_extraction.v1.schema.json",
    "contracts/schemas/service/nex_cx/chunk_set.v1.schema.json",
    "contracts/schemas/service/nex_cx/embedding_index.v1.schema.json",
    "contracts/schemas/service/nex_cx/lexical_index.v1.schema.json",
    "contracts/schemas/service/nex_cx/document_summary.v1.schema.json",
    "contracts/schemas/service/nex_cx/document_summary_embedding.v1.schema.json",
    "contracts/schemas/service/nex_cx/retrieval_context_package.v1.schema.json",
    "contracts/schemas/service/nex_cx/document_library_projection.v1.schema.json",
    "contracts/schemas/service/nex_cx/document_detail_projection.v1.schema.json",
)

REQUIRED_CHECKPOINT_PATHS = (
    "docs/slices/0161_cx_persistence_gap_audit_refactoring_checkpoint.md",
    "docs/slices/0171_cx_retrieval_runtime_persistence_decision.md",
    "docs/slices/0290_cx_real_document_processing_pipeline_postgresql_smoke.md",
    "docs/slices/0311_cx_grounded_generation_boundary_audit_refactoring_checkpoint.md",
)


@dataclass(frozen=True)
class AgCxTransitionHandoffError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ag_cx_transition_handoff_candidate(
    *,
    generated_at: datetime,
    root: Path = ROOT,
) -> dict[str, Any]:
    normalized_time = _normalize_time(generated_at)
    assets = [
        _asset_projection(root, path, "contract")
        for path in REQUIRED_CONTRACT_PATHS
    ]
    checkpoints = [
        _asset_projection(root, path, "checkpoint")
        for path in REQUIRED_CHECKPOINT_PATHS
    ]
    body = {
        "handoff_schema_version": AG_CX_TRANSITION_HANDOFF_SCHEMA_VERSION,
        "source_service": "nex-ag",
        "target_service": "nex-cx",
        "next_requirement": "S91",
        "recommended_entrypoint": (
            "cx_current_state_reaudit_and_refactoring_checkpoint"
        ),
        "generated_at": _timestamp(normalized_time),
        "acceptance_policy_id": AG_MVP_ACCEPTANCE_POLICY_ID,
        "acceptance_binding_status": "PENDING",
        "manifest_status": "SEALED",
        "assets": assets,
        "checkpoints": checkpoints,
        "service_dependencies": [
            {
                "service_id": "nex-oa",
                "purpose": "subject_identity_and_owner_scope",
            },
            {
                "service_id": "nex-ae-api",
                "purpose": "upload_chat_and_document_detail_handoff",
            },
            {
                "service_id": "nex-mo",
                "purpose": "embedding_reranking_and_generation_provider_execution",
            },
        ],
        "ownership_boundaries": [
            "cx_owns_content_metadata_and_processing_lineage",
            "cx_source_bytes_remain_outside_relational_blob_storage",
            "owner_scope_remains_tenant_type_tenant_id_user_id",
            "ag_consumes_redacted_cx_operations_without_mutating_cx_records",
        ],
        "deferred_risks": [
            "production_object_storage_provider_selection",
            "vector_store_physical_separation_at_scale",
            "live_provider_recertification_after_model_or_endpoint_change",
            "cx_load_capacity_and_disaster_recovery_certification",
        ],
        "privacy": {
            "raw_document_content_included": False,
            "raw_prompt_or_generation_included": False,
            "database_url_or_credentials_included": False,
            "local_absolute_paths_included": False,
        },
    }
    return {
        **body,
        "manifest_hash": _sha256(_canonical_json(body).encode("utf-8")),
    }


def bind_ag_cx_transition_handoff(
    candidate: Mapping[str, Any],
    acceptance_report: Mapping[str, Any],
    *,
    bound_at: datetime,
) -> dict[str, Any]:
    verification = verify_ag_cx_transition_handoff(candidate)
    if verification["status"] != "VERIFIED":
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.candidate_invalid",
            detail="CX handoff candidate must be verified before binding.",
        )
    _validate_acceptance_report(acceptance_report)
    normalized_time = _normalize_time(bound_at)
    body = {
        "attestation_schema_version": (
            AG_CX_TRANSITION_ATTESTATION_SCHEMA_VERSION
        ),
        "attestation_status": "BOUND",
        "source_service": "nex-ag",
        "target_service": "nex-cx",
        "manifest_hash": candidate["manifest_hash"],
        "acceptance_id": acceptance_report["acceptance_id"],
        "bound_at": _timestamp(normalized_time),
        "transition_status": "READY_FOR_CX",
        "raw_evidence_included": False,
    }
    return {
        **body,
        "attestation_hash": _sha256(_canonical_json(body).encode("utf-8")),
    }


def verify_ag_cx_transition_handoff(package: Any) -> dict[str, Any]:
    if not isinstance(package, Mapping):
        return _verification(False, "package_invalid")
    manifest_hash = package.get("manifest_hash")
    if not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        return _verification(False, "manifest_hash_invalid")
    body = {key: value for key, value in package.items() if key != "manifest_hash"}
    calculated = _sha256(_canonical_json(body).encode("utf-8"))
    if not _constant_time_equal(manifest_hash, calculated):
        return _verification(False, "manifest_hash_mismatch")
    if (
        package.get("handoff_schema_version")
        != AG_CX_TRANSITION_HANDOFF_SCHEMA_VERSION
        or package.get("source_service") != "nex-ag"
        or package.get("target_service") != "nex-cx"
        or package.get("manifest_status") != "SEALED"
        or package.get("acceptance_policy_id")
        != AG_MVP_ACCEPTANCE_POLICY_ID
        or package.get("acceptance_binding_status") != "PENDING"
    ):
        return _verification(False, "manifest_identity_invalid")
    return _verification(True, None)


def verify_ag_cx_transition_handoff_attestation(
    attestation: Any,
    *,
    candidate: Mapping[str, Any],
    acceptance_report: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(attestation, Mapping):
        return _attestation_verification(False, "attestation_invalid")
    attestation_hash = attestation.get("attestation_hash")
    if not isinstance(attestation_hash, str) or len(attestation_hash) != 64:
        return _attestation_verification(False, "attestation_hash_invalid")
    body = {
        key: value
        for key, value in attestation.items()
        if key != "attestation_hash"
    }
    calculated = _sha256(_canonical_json(body).encode("utf-8"))
    if not _constant_time_equal(attestation_hash, calculated):
        return _attestation_verification(False, "attestation_hash_mismatch")
    if (
        attestation.get("attestation_schema_version")
        != AG_CX_TRANSITION_ATTESTATION_SCHEMA_VERSION
        or attestation.get("attestation_status") != "BOUND"
        or attestation.get("manifest_hash") != candidate.get("manifest_hash")
        or attestation.get("acceptance_id")
        != acceptance_report.get("acceptance_id")
        or attestation.get("transition_status") != "READY_FOR_CX"
    ):
        return _attestation_verification(False, "attestation_binding_invalid")
    return _attestation_verification(True, None)


def _validate_acceptance_report(report: Mapping[str, Any]) -> None:
    if report.get("service_id") != "nex-ag":
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.acceptance_service_invalid",
            detail="CX handoff requires a NeX-AG acceptance report.",
        )
    if report.get("status") != "ACCEPTED" or report.get(
        "transition_status"
    ) != "READY_FOR_CX":
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.acceptance_not_ready",
            detail="CX handoff requires an accepted READY_FOR_CX report.",
        )
    acceptance_id = report.get("acceptance_id")
    if (
        not isinstance(acceptance_id, str)
        or len(acceptance_id) != 64
        or any(character not in "0123456789abcdef" for character in acceptance_id)
    ):
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.acceptance_id_invalid",
            detail="CX handoff requires a canonical acceptance ID.",
        )


def _asset_projection(root: Path, relative_path: str, kind: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.required_asset_missing",
            detail=f"Required CX handoff {kind} is missing: {relative_path}",
        )
    return {
        "kind": kind,
        "path": relative_path,
        "sha256": _sha256(path.read_bytes()),
    }


def _normalize_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AgCxTransitionHandoffError(
            error_code="ag.cx_handoff.generated_at_timezone_required",
            detail="CX handoff generated_at must be timezone-aware.",
        )
    return value.astimezone(UTC)


def _verification(valid: bool, failure_code: str | None) -> dict[str, Any]:
    return {
        "verification_schema_version": "ag_cx_transition_handoff_verification.v1",
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _attestation_verification(
    valid: bool, failure_code: str | None
) -> dict[str, Any]:
    return {
        "verification_schema_version": (
            "ag_cx_transition_handoff_attestation_verification.v1"
        ),
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _constant_time_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
