from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nex_cx.repository import DEFAULT_OWNER_USER_ID, DEFAULT_TENANT_ID
from nex_cx.source_ownership import (
    CX_SOURCE_OWNERSHIP_BOUNDARY_DECISION_SCHEMA_VERSION,
    CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION,
    OA_TENANT_SUBJECT_TYPE,
    OA_USER_SUBJECT_TYPE,
    build_source_ownership_boundary_decision,
    build_source_ownership_ref,
    ownership_ref_has_private_identity_payload,
    source_ownership_dedupe_key,
)


CONTRACT_ROOT = Path(__file__).parents[1] / "contracts"
SOURCE_SHA256 = "a" * 64


def source_ownership_decision_schema() -> dict[str, object]:
    return json.loads(
        (
            CONTRACT_ROOT
            / "schemas"
            / "service"
            / "nex_cx"
            / "source_ownership_boundary_decision.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def test_source_ownership_boundary_decision_requires_minimal_oa_subject_registry() -> None:
    decision = build_source_ownership_boundary_decision()

    Draft202012Validator(source_ownership_decision_schema()).validate(decision)
    assert (
        decision["decision_schema_version"]
        == CX_SOURCE_OWNERSHIP_BOUNDARY_DECISION_SCHEMA_VERSION
    )
    assert decision["decision_status"] == (
        "boundary_decided_oa_subject_registry_required"
    )
    assert decision["nex_oa_dependency"] == {
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
    }
    assert decision["canonical_fields"]["owner_subject_ref"]["type"] == (
        OA_USER_SUBJECT_TYPE
    )
    assert decision["canonical_fields"]["tenant_ref"]["type"] == (
        OA_TENANT_SUBJECT_TYPE
    )
    assert decision["duplicate_policy"] == {
        "same_owner_same_hash": "return_existing_document",
        "different_owner_same_hash": "create_distinct_content_object",
        "cross_owner_existing_document_id_visible": False,
        "source_file_metadata_shared_by_hash": True,
    }
    assert decision["next_slice"] == "0197_cx_upload_canonical_ownership_intake"
    assert decision["migration_sequence"][-1]["slice"] == "0197"


def test_source_ownership_ref_maps_legacy_owner_fields_to_oa_subject_refs() -> None:
    ownership = build_source_ownership_ref(
        tenant_id=" tenant-a ",
        owner_user_id=" user-a ",
        uploaded_by_user_id=" uploader-a ",
    )

    assert ownership == {
        "ownership_schema_version": CX_SOURCE_OWNERSHIP_REF_SCHEMA_VERSION,
        "tenant_ref": {"type": OA_TENANT_SUBJECT_TYPE, "id": "tenant-a"},
        "owner_subject_ref": {"type": OA_USER_SUBJECT_TYPE, "id": "user-a"},
        "uploaded_by_subject_ref": {
            "type": OA_USER_SUBJECT_TYPE,
            "id": "uploader-a",
        },
        "legacy": {"tenant_id": "tenant-a", "owner_user_id": "user-a"},
        "compatibility_mode": "legacy_owner_fields_mapped_to_oa_subject_refs",
    }
    assert source_ownership_dedupe_key(
        ownership,
        source_sha256=SOURCE_SHA256,
    ) == ("tenant-a", "user-a", SOURCE_SHA256)


def test_source_ownership_ref_defaults_uploaded_by_to_owner_for_mock_mode() -> None:
    ownership = build_source_ownership_ref()

    assert ownership["tenant_ref"]["id"] == DEFAULT_TENANT_ID
    assert ownership["owner_subject_ref"]["id"] == DEFAULT_OWNER_USER_ID
    assert ownership["uploaded_by_subject_ref"] == ownership["owner_subject_ref"]
    assert ownership_ref_has_private_identity_payload(ownership) is False


@pytest.mark.parametrize(
    ("kwargs", "field_name"),
    [
        ({"tenant_id": ""}, "tenant_id"),
        ({"owner_user_id": " "}, "owner_user_id"),
        ({"uploaded_by_user_id": 123}, "uploaded_by_user_id"),
    ],
)
def test_source_ownership_ref_rejects_invalid_legacy_subject_values(
    kwargs: dict[str, object],
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        build_source_ownership_ref(**kwargs)


def test_source_ownership_dedupe_key_requires_subject_ids_and_hash() -> None:
    ownership = build_source_ownership_ref(tenant_id="tenant-a", owner_user_id="user-a")

    with pytest.raises(ValueError, match="owner_subject_ref.id"):
        source_ownership_dedupe_key(
            {**ownership, "owner_subject_ref": {"type": OA_USER_SUBJECT_TYPE}},
            source_sha256=SOURCE_SHA256,
        )
    with pytest.raises(ValueError, match="source_sha256"):
        source_ownership_dedupe_key(ownership, source_sha256=" ")


def test_source_ownership_private_identity_payload_guard_flags_unsafe_fields() -> None:
    assert ownership_ref_has_private_identity_payload(
        {
            "owner_subject_ref": {"type": OA_USER_SUBJECT_TYPE, "id": "user-a"},
            "access_token": "secret",
        }
    )
    assert ownership_ref_has_private_identity_payload(
        {"email": "user@example.com"}
    )
