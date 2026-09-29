from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
AE_OPERATIONS_HANDOFF_SCHEMA_VERSION = "ae_mvp_operations_handoff.v1"
AE_OPERATIONS_ATTESTATION_SCHEMA_VERSION = (
    "ae_mvp_operations_handoff_attestation.v1"
)
AE_MVP_ACCEPTANCE_POLICY_ID = "ae-mvp-acceptance-v1"

REQUIRED_ASSET_PATHS = (
    "contracts/schemas/service/nex_ae_api/mvp_acceptance.v1.schema.json",
    "contracts/openapi/nex-ae-api.openapi.yaml",
    "docs/development_process.md",
    "docs/slices/1091_s109_ae_web_grounded_generation_experience_closure.md",
    "docs/slices/1092_ae_mvp_acceptance_operations_boundary_audit.md",
    "docs/slices/1093_ae_mvp_acceptance_policy.md",
    "docs/slices/1094_ae_mvp_evidence_inventory.md",
    "docs/slices/1095_ae_mvp_acceptance_evaluator.md",
    "docs/slices/1096_ae_mvp_acceptance_api.md",
    "docs/slices/1097_ae_mvp_acceptance_contract_hardening.md",
    "docs/slices/1098_ae_mvp_operations_handoff.md",
    "docs/slices/1099_ae_mvp_acceptance_postgres_live_smoke.md",
    "docs/slices/1100_ae_mvp_acceptance_operator_runbook.md",
    "docs/slices/1101_s110_ae_mvp_acceptance_operations_closure.md",
)


@dataclass(frozen=True)
class AeMvpOperationsHandoffError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ae_mvp_operations_handoff_candidate(
    *,
    generated_at: datetime,
    root: Path = ROOT,
) -> dict[str, Any]:
    normalized_time = _normalize_time(generated_at)
    assets = [_asset_projection(root, path) for path in REQUIRED_ASSET_PATHS]
    body = {
        "handoff_schema_version": AE_OPERATIONS_HANDOFF_SCHEMA_VERSION,
        "source_service": "nex-ae-api",
        "web_service": "nex-ae-web",
        "target_service": "nex-ag",
        "operations_scope": "nex_ae_service_mvp",
        "generated_at": _timestamp(normalized_time),
        "acceptance_policy_id": AE_MVP_ACCEPTANCE_POLICY_ID,
        "acceptance_binding_status": "PENDING",
        "manifest_status": "SEALED",
        "assets": assets,
        "read_model": {
            "path": "/admin/v1/operations/mvp-acceptance",
            "method": "GET",
            "server_selected": True,
            "ag_direct_ae_database_access_allowed": False,
        },
        "service_dependencies": [
            {"service_id": "nex-oa", "purpose": "identity_and_owner_scope"},
            {"service_id": "nex-cx", "purpose": "grounded_generation"},
            {"service_id": "nex-mo", "purpose": "provider_execution"},
        ],
        "ownership_boundaries": [
            "ae_retains_workspace_chat_response_and_artifact_records",
            "ag_reads_only_redacted_ae_operations_projections",
            "ag_never_queries_nex_ae_database_directly",
            "private_content_remains_outside_operations_evidence",
        ],
        "operator_entrypoints": [
            "acceptance_projection",
            "service_health_and_readiness",
            "job_control_and_service_logs",
            "scheduler_and_worker_operations",
        ],
        "deferred_risks": [
            "production_identity_provider_activation",
            "production_object_storage_activation",
            "distributed_load_certification",
            "disaster_recovery_certification",
        ],
        "privacy": {
            "raw_prompt_or_response_included": False,
            "raw_document_or_artifact_included": False,
            "database_url_or_credentials_included": False,
            "provider_endpoint_or_key_included": False,
            "local_absolute_paths_included": False,
        },
    }
    return {**body, "manifest_hash": _sha256(_canonical_json(body).encode())}


def verify_ae_mvp_operations_handoff(package: Any) -> dict[str, Any]:
    if not isinstance(package, Mapping):
        return _verification(False, "package_invalid")
    manifest_hash = package.get("manifest_hash")
    if not _canonical_hash(manifest_hash):
        return _verification(False, "manifest_hash_invalid")
    body = {key: value for key, value in package.items() if key != "manifest_hash"}
    calculated = _sha256(_canonical_json(body).encode())
    if not hmac.compare_digest(manifest_hash, calculated):
        return _verification(False, "manifest_hash_mismatch")
    if (
        package.get("handoff_schema_version")
        != AE_OPERATIONS_HANDOFF_SCHEMA_VERSION
        or package.get("source_service") != "nex-ae-api"
        or package.get("web_service") != "nex-ae-web"
        or package.get("target_service") != "nex-ag"
        or package.get("manifest_status") != "SEALED"
        or package.get("acceptance_policy_id") != AE_MVP_ACCEPTANCE_POLICY_ID
        or package.get("acceptance_binding_status") != "PENDING"
    ):
        return _verification(False, "manifest_identity_invalid")
    return _verification(True, None)


def bind_ae_mvp_operations_handoff(
    candidate: Mapping[str, Any],
    acceptance_report: Mapping[str, Any],
    *,
    bound_at: datetime,
) -> dict[str, Any]:
    if verify_ae_mvp_operations_handoff(candidate)["status"] != "VERIFIED":
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.candidate_invalid",
            detail="Operations handoff candidate must be verified before binding.",
        )
    _validate_acceptance_report(acceptance_report)
    normalized_time = _normalize_time(bound_at)
    body = {
        "attestation_schema_version": AE_OPERATIONS_ATTESTATION_SCHEMA_VERSION,
        "attestation_status": "BOUND",
        "source_service": "nex-ae-api",
        "target_service": "nex-ag",
        "manifest_hash": candidate["manifest_hash"],
        "acceptance_id": acceptance_report["acceptance_id"],
        "bound_at": _timestamp(normalized_time),
        "operations_status": "READY_FOR_OPERATIONS",
        "raw_evidence_included": False,
    }
    return {**body, "attestation_hash": _sha256(_canonical_json(body).encode())}


def verify_ae_mvp_operations_handoff_attestation(
    attestation: Any,
    *,
    candidate: Mapping[str, Any],
    acceptance_report: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(attestation, Mapping):
        return _attestation_verification(False, "attestation_invalid")
    attestation_hash = attestation.get("attestation_hash")
    if not _canonical_hash(attestation_hash):
        return _attestation_verification(False, "attestation_hash_invalid")
    body = {
        key: value for key, value in attestation.items() if key != "attestation_hash"
    }
    calculated = _sha256(_canonical_json(body).encode())
    if not hmac.compare_digest(attestation_hash, calculated):
        return _attestation_verification(False, "attestation_hash_mismatch")
    if (
        attestation.get("attestation_schema_version")
        != AE_OPERATIONS_ATTESTATION_SCHEMA_VERSION
        or attestation.get("attestation_status") != "BOUND"
        or attestation.get("manifest_hash") != candidate.get("manifest_hash")
        or attestation.get("acceptance_id") != acceptance_report.get("acceptance_id")
        or attestation.get("operations_status") != "READY_FOR_OPERATIONS"
    ):
        return _attestation_verification(False, "attestation_binding_invalid")
    return _attestation_verification(True, None)


def _validate_acceptance_report(report: Mapping[str, Any]) -> None:
    if report.get("service_id") != "nex-ae-api":
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.acceptance_service_invalid",
            detail="Operations handoff requires a NeX-AE acceptance report.",
        )
    if report.get("status") != "ACCEPTED" or report.get(
        "operations_status"
    ) != "READY_FOR_OPERATIONS":
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.acceptance_not_ready",
            detail="Operations handoff requires an accepted operations-ready report.",
        )
    if not _canonical_hash(report.get("acceptance_id")):
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.acceptance_id_invalid",
            detail="Operations handoff requires a canonical acceptance ID.",
        )


def _asset_projection(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.required_asset_missing",
            detail=f"Required operations handoff asset is missing: {relative_path}",
        )
    return {"path": relative_path, "sha256": _sha256(path.read_bytes())}


def _normalize_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AeMvpOperationsHandoffError(
            error_code="ae.operations_handoff.timezone_required",
            detail="Operations handoff time must be timezone-aware.",
        )
    return value.astimezone(UTC)


def _canonical_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _verification(valid: bool, failure_code: str | None) -> dict[str, Any]:
    return {
        "verification_schema_version": "ae_mvp_operations_handoff_verification.v1",
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _attestation_verification(
    valid: bool, failure_code: str | None
) -> dict[str, Any]:
    return {
        "verification_schema_version": (
            "ae_mvp_operations_handoff_attestation_verification.v1"
        ),
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
