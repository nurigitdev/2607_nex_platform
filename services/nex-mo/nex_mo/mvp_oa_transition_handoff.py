from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nex_mo.mvp_acceptance import MO_MVP_ACCEPTANCE_POLICY_ID


ROOT = Path(__file__).resolve().parents[3]
MO_OA_HANDOFF_SCHEMA_VERSION = "mo_mvp_oa_transition_handoff.v1"
MO_OA_ATTESTATION_SCHEMA_VERSION = "mo_mvp_oa_transition_attestation.v1"

REQUIRED_ASSET_PATHS = (
    "contracts/schemas/service/nex_mo/mvp_acceptance.v1.schema.json",
    "contracts/openapi/nex-mo.openapi.yaml",
    "docs/development_process.md",
    "docs/slices/1191_s119_mo_operations_integration_acceptance_closure.md",
    "docs/slices/1192_mo_mvp_acceptance_oa_transition_boundary_audit.md",
    "docs/slices/1193_mo_mvp_acceptance_policy.md",
    "docs/slices/1194_mo_mvp_evidence_inventory.md",
    "docs/slices/1195_mo_mvp_acceptance_evaluator.md",
    "docs/slices/1196_mo_mvp_acceptance_api.md",
    "docs/slices/1197_mo_mvp_acceptance_contract_hardening.md",
    "docs/slices/1198_mo_mvp_oa_transition_handoff.md",
)

PRIVACY_FLAGS = {
    "raw_provider_telemetry_included": False,
    "database_url_or_credentials_included": False,
    "provider_endpoint_or_key_included": False,
    "local_absolute_paths_included": False,
    "user_identity_payload_included": False,
}


@dataclass(frozen=True)
class MoMvpOaTransitionHandoffError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_mo_mvp_oa_transition_candidate(
    *,
    generated_at: datetime,
    root: Path = ROOT,
) -> dict[str, Any]:
    normalized_time = _normalize_time(generated_at)
    assets = [_asset_projection(root, path) for path in REQUIRED_ASSET_PATHS]
    body = {
        "handoff_schema_version": MO_OA_HANDOFF_SCHEMA_VERSION,
        "source_service": "nex-mo",
        "target_service": "nex-oa",
        "transition_scope": "nex_mo_service_mvp",
        "generated_at": _timestamp(normalized_time),
        "acceptance_policy_id": MO_MVP_ACCEPTANCE_POLICY_ID,
        "acceptance_binding_status": "PENDING",
        "manifest_status": "SEALED",
        "assets": assets,
        "read_model": {
            "path": "/admin/v1/operations/mvp-acceptance",
            "method": "GET",
            "server_selected": True,
            "oa_direct_mo_database_access_allowed": False,
        },
        "oa_contract": {
            "service_audience": "nex-mo",
            "service_scope_required": True,
            "stable_tenant_subject_refs_required": True,
            "stable_user_subject_refs_required": True,
            "admin_role_required_for_user_access": True,
        },
        "model_aliases": {
            "embedding": "Qwen3-Embedding-4B",
            "reranking": "Qwen3-Reranker-4B",
            "generation": "Qwen3.5-4B",
        },
        "ownership_boundaries": [
            "mo_retains_provider_catalog_alias_telemetry_and_runtime_records",
            "oa_retains_identity_credential_membership_and_session_records",
            "oa_reads_only_redacted_mo_acceptance_projections",
            "oa_never_queries_nex_mo_database_directly",
        ],
        "oa_entrypoint": {
            "requirement": "S121",
            "capability": "oa_current_state_reaudit_and_refactoring_checkpoint",
        },
        "deferred_risks": [
            "production_identity_provider_activation",
            "external_metrics_backend_activation",
            "distributed_load_certification",
            "disaster_recovery_certification",
        ],
        "privacy": dict(PRIVACY_FLAGS),
    }
    return {**body, "manifest_hash": _sha256(_canonical_json(body).encode())}


def verify_mo_mvp_oa_transition_handoff(package: Any) -> dict[str, Any]:
    if not isinstance(package, Mapping):
        return _verification(False, "package_invalid")
    manifest_hash = package.get("manifest_hash")
    if not _canonical_hash(manifest_hash):
        return _verification(False, "manifest_hash_invalid")
    body = {key: value for key, value in package.items() if key != "manifest_hash"}
    calculated = _sha256(_canonical_json(body).encode())
    if not hmac.compare_digest(manifest_hash, calculated):
        return _verification(False, "manifest_hash_mismatch")
    read_model = _mapping(package.get("read_model"))
    if (
        package.get("handoff_schema_version") != MO_OA_HANDOFF_SCHEMA_VERSION
        or package.get("source_service") != "nex-mo"
        or package.get("target_service") != "nex-oa"
        or package.get("manifest_status") != "SEALED"
        or package.get("acceptance_policy_id") != MO_MVP_ACCEPTANCE_POLICY_ID
        or package.get("acceptance_binding_status") != "PENDING"
        or read_model.get("oa_direct_mo_database_access_allowed") is not False
        or package.get("privacy") != PRIVACY_FLAGS
    ):
        return _verification(False, "manifest_identity_invalid")
    return _verification(True, None)


def bind_mo_mvp_oa_transition_handoff(
    candidate: Mapping[str, Any],
    acceptance_report: Mapping[str, Any],
    *,
    bound_at: datetime,
) -> dict[str, Any]:
    if verify_mo_mvp_oa_transition_handoff(candidate)["status"] != "VERIFIED":
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.candidate_invalid",
            detail="OA transition handoff candidate must be verified before binding.",
        )
    _validate_acceptance_report(acceptance_report)
    body = {
        "attestation_schema_version": MO_OA_ATTESTATION_SCHEMA_VERSION,
        "attestation_status": "BOUND",
        "source_service": "nex-mo",
        "target_service": "nex-oa",
        "manifest_hash": candidate["manifest_hash"],
        "acceptance_id": acceptance_report["acceptance_id"],
        "bound_at": _timestamp(_normalize_time(bound_at)),
        "transition_status": "READY_FOR_OA",
        "raw_evidence_included": False,
    }
    return {**body, "attestation_hash": _sha256(_canonical_json(body).encode())}


def verify_mo_mvp_oa_transition_attestation(
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
        != MO_OA_ATTESTATION_SCHEMA_VERSION
        or attestation.get("attestation_status") != "BOUND"
        or attestation.get("source_service") != "nex-mo"
        or attestation.get("target_service") != "nex-oa"
        or attestation.get("manifest_hash") != candidate.get("manifest_hash")
        or attestation.get("acceptance_id") != acceptance_report.get("acceptance_id")
        or attestation.get("transition_status") != "READY_FOR_OA"
        or attestation.get("raw_evidence_included") is not False
    ):
        return _attestation_verification(False, "attestation_binding_invalid")
    return _attestation_verification(True, None)


def _validate_acceptance_report(report: Mapping[str, Any]) -> None:
    if report.get("service_id") != "nex-mo":
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.acceptance_service_invalid",
            detail="OA transition handoff requires a NeX-MO acceptance report.",
        )
    if (
        report.get("status") != "ACCEPTED"
        or report.get("transition_status") != "READY_FOR_OA"
        or report.get("transition_target") != "nex-oa"
    ):
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.acceptance_not_ready",
            detail="OA transition handoff requires an accepted OA-ready report.",
        )
    if not _canonical_hash(report.get("acceptance_id")):
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.acceptance_id_invalid",
            detail="OA transition handoff requires a canonical acceptance ID.",
        )


def _asset_projection(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    if not path.is_file():
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.required_asset_missing",
            detail=f"Required OA transition asset is missing: {relative_path}",
        )
    return {"path": relative_path, "sha256": _sha256(path.read_bytes())}


def _normalize_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MoMvpOaTransitionHandoffError(
            error_code="mo.oa_transition_handoff.timezone_required",
            detail="OA transition handoff time must be timezone-aware.",
        )
    return value.astimezone(UTC)


def _canonical_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _verification(valid: bool, failure_code: str | None) -> dict[str, Any]:
    return {
        "verification_schema_version": "mo_mvp_oa_transition_handoff_verification.v1",
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _attestation_verification(
    valid: bool,
    failure_code: str | None,
) -> dict[str, Any]:
    return {
        "verification_schema_version": "mo_mvp_oa_transition_attestation_verification.v1",
        "status": "VERIFIED" if valid else "INVALID",
        "failure_code": failure_code,
    }


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
