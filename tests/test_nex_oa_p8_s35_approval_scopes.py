from __future__ import annotations

import pytest
from nex_oa.authorization import OaAuthorizationError, normalize_authorization_scopes
from nex_oa.authorization_resolver import (
    OA_APPROVAL_DECIDE_SCOPE,
    OA_APPROVAL_READ_SCOPE,
    OA_APPROVAL_SCOPES,
    require_approval_scope,
    resolve_effective_authorization,
)
from nex_oa.memberships import DEFAULT_MEMBERSHIP_SCOPES


def _membership(*, status="ACTIVE", scopes=(), roles=()):
    return {
        "tenant_id": "tenant-p8",
        "subject_id": "user-approver",
        "status": status,
        "roles": list(roles),
        "scopes": list(scopes),
        "revision": 3,
    }


def _inputs(*, role_scopes=()):
    roles = []
    if role_scopes:
        roles.append(
            {
                "tenant_id": "tenant-p8",
                "role_id": "approval-reviewer",
                "status": "ACTIVE",
                "scopes": list(role_scopes),
                "revision": 7,
            }
        )
    return {"roles": roles, "groups": [], "group_members": [], "group_roles": []}


def test_s35_canonical_approval_scopes_use_existing_resource_action_model():
    assert OA_APPROVAL_SCOPES == {"approval:read", "approval:decide"}
    assert normalize_authorization_scopes(
        [OA_APPROVAL_DECIDE_SCOPE, OA_APPROVAL_READ_SCOPE]
    ) == (OA_APPROVAL_DECIDE_SCOPE, OA_APPROVAL_READ_SCOPE)


def test_s35_direct_membership_grant_can_authorize_each_scope_independently():
    read_only = resolve_effective_authorization(
        _membership(scopes=[OA_APPROVAL_READ_SCOPE]),
        inputs=_inputs(),
    )
    require_approval_scope(read_only, required_scope=OA_APPROVAL_READ_SCOPE)
    with pytest.raises(OaAuthorizationError) as denied:
        require_approval_scope(read_only, required_scope=OA_APPROVAL_DECIDE_SCOPE)
    assert denied.value.error_code == "oa.authorization_scope_not_granted"
    assert denied.value.status_code == 403


def test_s35_active_role_grant_is_resolved_without_a_separate_permission_store():
    authorization = resolve_effective_authorization(
        _membership(roles=["approval-reviewer"]),
        inputs=_inputs(role_scopes=OA_APPROVAL_SCOPES),
    )
    require_approval_scope(authorization, required_scope=OA_APPROVAL_READ_SCOPE)
    require_approval_scope(authorization, required_scope=OA_APPROVAL_DECIDE_SCOPE)
    assert authorization["roles"] == ("approval-reviewer",)
    assert authorization["scopes"] == (
        OA_APPROVAL_DECIDE_SCOPE,
        OA_APPROVAL_READ_SCOPE,
    )
    assert authorization["source_counts"]["effective_scope_count"] == 2


def test_s35_inactive_membership_and_unknown_approval_scope_fail_closed():
    with pytest.raises(OaAuthorizationError) as inactive:
        resolve_effective_authorization(
            _membership(status="DISABLED", scopes=OA_APPROVAL_SCOPES),
            inputs=_inputs(),
        )
    assert inactive.value.error_code == "oa.authorization_membership_inactive"
    assert inactive.value.status_code == 403

    authorization = resolve_effective_authorization(
        _membership(scopes=OA_APPROVAL_SCOPES), inputs=_inputs()
    )
    with pytest.raises(OaAuthorizationError) as invalid:
        require_approval_scope(
            authorization,
            required_scope="approval:admin",
        )
    assert invalid.value.error_code == "oa.approval_scope_invalid"
    assert invalid.value.status_code == 400


def test_s35_approval_scopes_are_never_silently_added_to_default_membership():
    assert OA_APPROVAL_READ_SCOPE not in DEFAULT_MEMBERSHIP_SCOPES
    assert OA_APPROVAL_DECIDE_SCOPE not in DEFAULT_MEMBERSHIP_SCOPES
