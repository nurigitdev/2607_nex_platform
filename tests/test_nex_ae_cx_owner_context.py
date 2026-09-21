from __future__ import annotations

from nex_ae_api.cx_owner_context import (
    CX_SUBJECT_HEADER,
    CX_TENANT_HEADER,
    cx_owner_headers,
    cx_owner_scope_from_payload,
)


def test_owner_headers_normalize_values_and_fail_to_local_defaults() -> None:
    assert cx_owner_headers(" tenant-001 ", " user-001 ") == {
        CX_TENANT_HEADER: "tenant-001",
        CX_SUBJECT_HEADER: "user-001",
    }
    assert cx_owner_headers(None, " ") == {
        CX_TENANT_HEADER: "local-tenant",
        CX_SUBJECT_HEADER: "local-user",
    }


def test_owner_scope_prefers_canonical_ownership_ref() -> None:
    assert cx_owner_scope_from_payload(
        {
            "ownership_ref": {
                "tenant_ref": {"type": "oa.tenant", "id": "tenant-canonical"},
                "owner_subject_ref": {"type": "oa.user", "id": "user-canonical"},
            },
            "tenant_id": "tenant-alias",
            "owner_user_id": "user-alias",
        }
    ) == ("tenant-canonical", "user-canonical")


def test_owner_scope_supports_actor_alias_and_local_fallbacks() -> None:
    assert cx_owner_scope_from_payload(
        {
            "actor_claims_ref": {
                "tenant_id": "tenant-actor",
                "actor_id": "user-actor",
            }
        }
    ) == ("tenant-actor", "user-actor")
    assert cx_owner_scope_from_payload(
        {"tenant_id": "tenant-flat", "user_id": "user-flat"}
    ) == ("tenant-flat", "user-flat")
    assert cx_owner_scope_from_payload({}) == ("local-tenant", "local-user")

