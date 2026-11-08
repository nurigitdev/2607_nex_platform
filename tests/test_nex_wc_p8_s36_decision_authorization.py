from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nex_wc.approvals import (
    ApprovalDecisionAuthorizationError,
    ApprovalDecisionAuthorizer,
)
from nex_wc.authorization import AuthorizationSubjectDenied


def _work_item(**overrides):
    value = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8",
        "approval_work_item_id": "36000000-0000-4000-8000-000000000001",
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-s36",
        "semantic_hash": "sha256:" + "6" * 64,
        "title": "Approve protected WRITE",
        "display_safe_summary": "Create the approved voucher draft.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-s36",
        "target_approver_ref": "approver-s36",
        "target_role_ref": None,
        "target_org_scope_ref": "org-finance",
        "target_project_scope_ref": "project-p8",
        "agent_execution_id": "agent-execution-s36",
        "executable_step_id": "step-s36",
        "nsl_execution_id": "nsl-execution-s36",
        "business_operation_id": "operation-s36",
        "approval_request_id": "approval-request-s36",
        "protected_request_ref": "ae-private:approval-request-s36",
        "resume_target_ref": "ae-wait:approval-request-s36",
        "state": "PENDING",
        "created_at": "2026-10-22T11:00:00Z",
        "expires_at": "2026-10-23T11:00:00Z",
        "version": 1,
    }
    value.update(overrides)
    return value


class _AuthorizationSource:
    def __init__(self, value=None, *, error=None):
        self.value = value or {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s36",
            "scopes": ["approval:read", "approval:decide"],
            "roles": ["finance-approver"],
            "org_scope_refs": ["org-finance"],
            "project_scope_refs": ["project-p8"],
            "revision_hash": "a" * 64,
        }
        self.error = error
        self.calls = []

    def effective_authorization(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.value


def _authorizer(source):
    return ApprovalDecisionAuthorizer(
        source,
        clock=lambda: datetime(2026, 10, 22, 11, 30, tzinfo=UTC),
    )


def test_s36_exact_target_principal_is_freshly_authorized_with_safe_evidence():
    source = _AuthorizationSource()
    authorizer = _authorizer(source)
    first = authorizer.authorize(work_item=_work_item(), decided_by="approver-s36")
    second = authorizer.authorize(work_item=_work_item(), decided_by="approver-s36")

    assert len(source.calls) == 2
    assert source.calls[0] == {
        "tenant_id": "tenant-p8",
        "subject_id": "approver-s36",
    }
    assert first == second == {
        "authorized_by_oa": True,
        "decided_by": "approver-s36",
        "oa_decision_ref": "oa-authz:" + "a" * 64,
        "authorization_revision_hash": "sha256:" + "a" * 64,
        "authorization_checked_at": "2026-10-22T11:30:00Z",
    }
    assert "token" not in first


def test_s36_role_org_project_target_requires_every_configured_scope():
    item = _work_item(
        target_approver_ref=None,
        target_role_ref="finance-approver",
    )
    source = _AuthorizationSource()
    assert _authorizer(source).authorize(
        work_item=item, decided_by="approver-s36"
    )["authorized_by_oa"] is True

    for field, value in (
        ("roles", []),
        ("org_scope_refs", []),
        ("project_scope_refs", "project-p8"),
    ):
        denied_source = _AuthorizationSource({**source.value, field: value})
        with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
            _authorizer(denied_source).authorize(
                work_item=item, decided_by="approver-s36"
            )
        assert denied.value.error_code == "wc.approval_authorization_denied"


@pytest.mark.parametrize(
    "authorization",
    (
        None,
        {
            "active": False,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s36",
            "scopes": ["approval:decide"],
            "revision_hash": "a" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s36",
            "scopes": ["approval:read"],
            "revision_hash": "a" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-other",
            "subject_id": "approver-s36",
            "scopes": ["approval:decide"],
            "revision_hash": "a" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "other-subject",
            "scopes": ["approval:decide"],
            "revision_hash": "a" * 64,
        },
        {
            "active": True,
            "tenant_id": "tenant-p8",
            "subject_id": "approver-s36",
            "scopes": ["approval:decide"],
            "revision_hash": "malformed",
        },
    ),
)
def test_s36_inactive_missing_scope_and_malformed_identity_fail_closed(authorization):
    source = _AuthorizationSource(authorization)
    if authorization is None:
        source.value = None
    with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
        _authorizer(source).authorize(
            work_item=_work_item(), decided_by="approver-s36"
        )
    assert denied.value.status_code == 403
    assert denied.value.retryable is False


def test_s36_target_principal_mismatch_and_missing_target_fail_closed():
    source = _AuthorizationSource(
        {**_AuthorizationSource().value, "subject_id": "other-approver"}
    )
    authorizer = _authorizer(source)
    with pytest.raises(ApprovalDecisionAuthorizationError) as mismatch:
        authorizer.authorize(work_item=_work_item(), decided_by="other-approver")
    assert mismatch.value.status_code == 403

    authorizer = _authorizer(_AuthorizationSource())
    with pytest.raises(ApprovalDecisionAuthorizationError) as absent:
        authorizer.authorize(
            work_item=_work_item(
                target_approver_ref=None,
                target_role_ref=None,
                target_org_scope_ref=None,
                target_project_scope_ref=None,
            ),
            decided_by="approver-s36",
        )
    assert "no decision target" in str(absent.value)


def test_s36_typed_denial_and_dependency_failure_are_distinct():
    denied_source = _AuthorizationSource(
        error=AuthorizationSubjectDenied("inactive membership")
    )
    with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
        _authorizer(denied_source).authorize(
            work_item=_work_item(), decided_by="approver-s36"
        )
    assert denied.value.status_code == 403
    assert denied.value.retryable is False

    unavailable_source = _AuthorizationSource(error=RuntimeError("OA offline"))
    with pytest.raises(ApprovalDecisionAuthorizationError) as unavailable:
        _authorizer(unavailable_source).authorize(
            work_item=_work_item(), decided_by="approver-s36"
        )
    assert unavailable.value.error_code == "wc.approval_authorization_unavailable"
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_s36_explicit_oa_decision_ref_and_prefixed_hash_are_preserved():
    source = _AuthorizationSource(
        {
            **_AuthorizationSource().value,
            "revision_hash": "sha256:" + "b" * 64,
            "decision_ref": "oa-decision-s36",
        }
    )
    evidence = _authorizer(source).authorize(
        work_item=_work_item(), decided_by="approver-s36"
    )
    assert evidence["authorization_revision_hash"] == "sha256:" + "b" * 64
    assert evidence["oa_decision_ref"] == "oa-decision-s36"


def test_s36_malformed_explicit_decision_ref_is_denied():
    source = _AuthorizationSource(
        {**_AuthorizationSource().value, "decision_ref": "not allowed"}
    )
    with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
        _authorizer(source).authorize(
            work_item=_work_item(), decided_by="approver-s36"
        )
    assert denied.value.error_code == "wc.approval_authorization_denied"
