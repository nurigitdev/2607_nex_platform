from __future__ import annotations

import pytest

from nex_ae_api.auth_guard import BrowserUserAuthContext
from nex_ae_api.route_auth import AeFacadeRouteAuthContext
from nex_ae_api.workspace_chat_auth import (
    OWNER_SCOPE_SCHEMA_VERSION,
    WorkspaceChatOwnerError,
    WorkspaceChatOwnerScope,
    browser_owner_scope,
    owner_scope_from_record,
    owner_scoped_payload,
    record_matches_owner,
    service_owner_scope_from_payload,
)


def browser_auth() -> AeFacadeRouteAuthContext:
    return AeFacadeRouteAuthContext(
        auth_mode="browser_user",
        browser_context=BrowserUserAuthContext(
            tenant_id="tenant-a",
            user_id="user-a",
            scopes=("user",),
            roles=("employee",),
        ),
    )


def test_browser_claim_normalizes_owner_and_rejects_mismatch() -> None:
    normalized, scope = owner_scoped_payload({"title": "Workspace"}, browser_auth())

    assert normalized["tenant_id"] == "tenant-a"
    assert normalized["owner_user_id"] == "user-a"
    assert normalized["user_id"] == "user-a"
    assert normalized["ownership_ref"]["owner_subject_ref"]["id"] == "user-a"
    assert scope.to_wire()["owner_scope_schema_version"] == OWNER_SCOPE_SCHEMA_VERSION
    assert scope.authority == "claim"

    with pytest.raises(WorkspaceChatOwnerError) as exc:
        owner_scoped_payload({"owner_user_id": "user-b"}, browser_auth())
    assert exc.value.status_code == 403
    assert exc.value.error_code == "ae.browser_owner_scope_mismatch"
    assert str(exc.value) == exc.value.detail


def test_service_scope_requires_explicit_matching_identifiers() -> None:
    service = AeFacadeRouteAuthContext(auth_mode="service")
    canonical = {
        "ownership_ref": {
            "tenant_ref": {"id": "tenant-a"},
            "owner_subject_ref": {"id": "user-a"},
        },
        "tenant_id": "tenant-a",
        "owner_user_id": "user-a",
    }
    normalized, scope = owner_scoped_payload(canonical, service)

    assert scope == WorkspaceChatOwnerScope("tenant-a", "user-a", "service_payload")
    assert normalized["user_id"] == "user-a"
    assert service_owner_scope_from_payload(
        {"tenant_id": "tenant-a", "user_id": "user-a"}
    ) == scope

    for payload in (
        {},
        {"tenant_id": "tenant-a"},
        {"owner_user_id": "user-a"},
    ):
        with pytest.raises(WorkspaceChatOwnerError) as exc:
            service_owner_scope_from_payload(payload)
        assert exc.value.error_code == "ae.workspace_chat_owner_scope_required"


def test_service_scope_rejects_canonical_alias_mismatch() -> None:
    base = {
        "ownership_ref": {
            "tenant_ref": {"id": "tenant-a"},
            "owner_subject_ref": {"id": "user-a"},
        }
    }
    for payload in (
        {**base, "tenant_id": "tenant-b", "owner_user_id": "user-a"},
        {**base, "tenant_id": "tenant-a", "owner_user_id": "user-b"},
    ):
        with pytest.raises(WorkspaceChatOwnerError) as exc:
            service_owner_scope_from_payload(payload)
        assert exc.value.status_code == 409
        assert exc.value.error_code == "ae.workspace_chat_owner_scope_mismatch"


def test_record_scope_and_visibility_fail_closed() -> None:
    scope = WorkspaceChatOwnerScope("tenant-a", "user-a", "claim")
    record = {"tenant_id": "tenant-a", "user_id": "user-a"}

    assert owner_scope_from_record(record).authority == "persisted_record"
    assert record_matches_owner(record, scope) is True
    assert record_matches_owner({**record, "user_id": "user-b"}, scope) is False
    assert record_matches_owner({}, scope) is False
    with pytest.raises(WorkspaceChatOwnerError) as exc:
        owner_scope_from_record({"tenant_id": "tenant-a"})
    assert exc.value.status_code == 500


def test_browser_owner_scope_is_optional_for_service_context() -> None:
    assert browser_owner_scope(browser_auth()) == WorkspaceChatOwnerScope(
        "tenant-a", "user-a", "claim"
    )
    assert browser_owner_scope(AeFacadeRouteAuthContext(auth_mode="service")) is None
