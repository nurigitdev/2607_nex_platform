from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nex_cx.repository import DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID


CX_SOURCE_OWNERSHIP_BOUNDARY_DECISION_SCHEMA_VERSION = (
    "cx_source_ownership_boundary_decision.v1"
)
CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION = "cx_source_ownership_ref.v1"
OA_USER_SUBJECT_TYPE = "oa.user"
OA_TENANT_SUBJECT_TYPE = "oa.tenant"
LEGACY_OWNER_USER_FIELD = "owner_user_id"
LEGACY_TENANT_FIELD = "tenant_id"


def build_source_ownership_boundary_decision() -> dict[str, Any]:
    return {
        "decision_schema_version": (
            CX_SOURCE_OWNERSHIP_BOUNDARY_DECISION_SCHEMA_VERSION
        ),
        "decision_slice": "0192",
        "service_id": "nex-cx",
        "decision_status": "boundary_decided_oa_subject_registry_required",
        "problem_statement": (
            "CX source file bytes are global metadata, but document ownership, "
            "ACLs, and duplicate upload behavior must be scoped to a stable "
            "OA account subject."
        ),
        "current_compatibility_fields": {
            "tenant_id": {
                "status": "compatibility_alias",
                "maps_to": "tenant_ref.id",
                "default": DEFAULT_TENANT_ID,
            },
            "owner_user_id": {
                "status": "compatibility_alias",
                "maps_to": "owner_subject_ref.id",
                "default": DEFAULT_OWNER_USER_ID,
            },
        },
        "canonical_fields": {
            "tenant_ref": {
                "type": OA_TENANT_SUBJECT_TYPE,
                "owner_service": "nex-oa",
                "required": True,
                "purpose": "tenant isolation and future workspace policy scope",
            },
            "owner_subject_ref": {
                "type": OA_USER_SUBJECT_TYPE,
                "owner_service": "nex-oa",
                "required": True,
                "purpose": "owner-scoped duplicate detection and read ownership",
            },
            "uploaded_by_subject_ref": {
                "type": OA_USER_SUBJECT_TYPE,
                "owner_service": "nex-oa",
                "required": True,
                "purpose": "audit attribution for the upload actor",
            },
        },
        "nex_oa_dependency": {
            "required_before_cx_schema_migration": True,
            "minimum_capability": "stable_subject_registry",
            "minimum_fields": [
                "tenant_ref",
                "subject_ref",
                "display_name",
                "status",
            ],
            "recommended_slice": "0193_nex_oa_subject_registry_foundation",
            "deferred": [
                "password_login",
                "external_identity_provider_mapping",
                "role_management",
                "full_user_profile",
            ],
        },
        "storage_boundary": {
            "cx_source_files": {
                "ownership": "global_source_byte_metadata",
                "dedupe_key": ["source_sha256"],
                "stores_raw_bytes": False,
                "local_storage_owner": "/data/nex-platform/cx/source-files",
                "future_object_storage_policy": "uri_and_hash_only",
            },
            "cx_content_objects": {
                "ownership": "logical_document_registration",
                "dedupe_key": [
                    "tenant_ref.id",
                    "owner_subject_ref.id",
                    "source_sha256",
                ],
                "compatibility_dedupe_key": [
                    "tenant_id",
                    "owner_user_id",
                    "source_sha256",
                ],
            },
            "cx_content_acl_entries": {
                "ownership": "permission_grants",
                "owner_grant": {
                    "principal_ref": "owner_subject_ref",
                    "permission": "owner",
                    "granted_by": "uploaded_by_subject_ref",
                },
            },
        },
        "duplicate_policy": {
            "same_owner_same_hash": "return_existing_document",
            "different_owner_same_hash": "create_distinct_content_object",
            "cross_owner_existing_document_id_visible": False,
            "source_file_metadata_shared_by_hash": True,
        },
        "migration_sequence": [
            {
                "slice": "0193",
                "work": "nex_oa_subject_registry_foundation",
                "reason": "CX needs stable OA subject ids before durable owner refs.",
            },
            {
                "slice": "0194",
                "work": "cx_source_ownership_schema_migration",
                "reason": (
                    "Add canonical subject ref columns while retaining legacy "
                    "tenant_id/owner_user_id compatibility."
                ),
            },
            {
                "slice": "0195",
                "work": "cx_owner_scoped_repository_api_wiring",
                "reason": "Write/read owner refs and preserve duplicate behavior.",
            },
            {
                "slice": "0196",
                "work": "ae_upload_ownership_propagation_contract",
                "reason": "AE must forward OA subject context to CX upload APIs.",
            },
            {
                "slice": "0197",
                "work": "cx_upload_canonical_ownership_intake",
                "reason": (
                    "CX upload registration should consume canonical owner "
                    "refs directly."
                ),
            },
            {
                "slice": "0198",
                "work": "oa_subject_registry_resolver_client",
                "reason": (
                    "AE/CX should resolve or verify OA subject refs before "
                    "live authentication integration."
                ),
            },
        ],
        "private_payload_policy": (
            "No raw source bytes, source text, extracted markdown, chunk text, "
            "summary text, vectors, prompts, or raw identity secrets are stored "
            "in ownership metadata."
        ),
        "next_slice": "0198_oa_subject_registry_resolver_client",
    }


def build_source_ownership_ref(
    *,
    tenant_id: str | None = None,
    owner_user_id: str | None = None,
    uploaded_by_user_id: str | None = None,
) -> dict[str, Any]:
    normalized_tenant_id = _non_empty_text(
        tenant_id,
        field_name="tenant_id",
        default=DEFAULT_TENANT_ID,
    )
    normalized_owner_user_id = _non_empty_text(
        owner_user_id,
        field_name="owner_user_id",
        default=DEFAULT_OWNER_USER_ID,
    )
    normalized_uploaded_by_user_id = _non_empty_text(
        uploaded_by_user_id,
        field_name="uploaded_by_user_id",
        default=normalized_owner_user_id,
    )
    return {
        "ownership_schema_version": CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": {
            "type": OA_TENANT_SUBJECT_TYPE,
            "id": normalized_tenant_id,
        },
        "owner_subject_ref": {
            "type": OA_USER_SUBJECT_TYPE,
            "id": normalized_owner_user_id,
        },
        "uploaded_by_subject_ref": {
            "type": OA_USER_SUBJECT_TYPE,
            "id": normalized_uploaded_by_user_id,
        },
        "legacy": {
            "tenant_id": normalized_tenant_id,
            "owner_user_id": normalized_owner_user_id,
        },
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }


def source_ownership_dedupe_key(
    ownership_ref: Mapping[str, Any],
    *,
    source_sha256: str,
) -> tuple[str, str, str]:
    tenant_ref = _mapping_value(ownership_ref.get("tenant_ref"))
    owner_subject_ref = _mapping_value(ownership_ref.get("owner_subject_ref"))
    return (
        _required_subject_id(tenant_ref, field_name="tenant_ref"),
        _required_subject_id(owner_subject_ref, field_name="owner_subject_ref"),
        _non_empty_text(source_sha256, field_name="source_sha256"),
    )


def ownership_ref_has_private_identity_payload(value: object) -> bool:
    serialized = repr(value).lower()
    private_terms = (
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "email",
        "phone",
        "raw_profile",
    )
    return any(term in serialized for term in private_terms)


def _mapping_value(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _required_subject_id(value: Mapping[str, Any], *, field_name: str) -> str:
    return _non_empty_text(value.get("id"), field_name=f"{field_name}.id")


def _non_empty_text(
    value: object,
    *,
    field_name: str,
    default: str | None = None,
) -> str:
    if value is None:
        if default is None:
            raise ValueError(f"{field_name} must be a non-empty string.")
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return normalized
