from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import test_nex_eos_p8_s58_fresh_authorization as s58
from fastapi.testclient import TestClient
from nex_ae_api import nsl_v02_public_api as public_api_module
from nex_ae_api.agent_runtime_worker import (
    LOCAL_SKILL_EXECUTOR,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerError,
    build_agent_runtime_worker_profile,
    validate_agent_runtime_worker_startup,
)
from nex_ae_api.auth_sessions import AUTH_SESSION_MODE_OA, SESSION_COOKIE_NAME
from nex_ae_api.nsl_backend_profiles import NSL_V02_IN_PROCESS_BACKEND
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiError
from nex_ae_api.voucher_attachment_api import register_voucher_attachment_routes
from nex_eos import (
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherAuthorizationClient,
    EosVoucherCommandError,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosVoucherRepository,
)
from nex_runtime import SERVICE_SPECS, build_service_app
from nex_wc.approvals import (
    ApprovalDecisionAuthorizationError,
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    InMemoryApprovalWorkItemRepository,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def test_invalid_package_trust_blocks_public_api_and_worker_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports = 0

    def unexpected_import():
        nonlocal imports
        imports += 1
        raise AssertionError("invalid package trust must block NSL import")

    monkeypatch.setattr(public_api_module, "_import_public_api", unexpected_import)
    failed_readiness = {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "FAIL",
        "failure_code": "ae.agent_runtime_worker.nsl_package_unready",
        "detail": "installed NSL wheel digest does not match lock",
    }

    with pytest.raises(NslV02PublicApiError) as public_api_denied:
        public_api_module.load_nsl_v02_public_api(failed_readiness)
    assert public_api_denied.value.error_code == "ae.nsl_v02.readiness_invalid"
    assert imports == 0

    config = AgentRuntimeWorkerConfig(
        mode="enabled",
        profile=build_agent_runtime_worker_profile(
            worker_id="ae-runtime-worker-p8-s84",
            declared_at="2026-10-24T12:00:00Z",
            supported_backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,),
        ),
    )
    with pytest.raises(AgentRuntimeWorkerError) as worker_denied:
        validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,),
            in_process_package_readiness=failed_readiness,
        )
    assert worker_denied.value.error_code == (
        "ae.agent_runtime_worker.nsl_package_unready"
    )


class _RevocableApprovalAuthorization:
    def __init__(self) -> None:
        self.scopes = {"approval:read", "approval:decide"}
        self.calls = 0

    def revoke(self, scope: str) -> None:
        self.scopes.discard(scope)

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls += 1
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes),
            "roles": ["employee"],
            "revision_hash": ("a" if "approval:decide" in self.scopes else "b")
            * 64,
        }


def _approval_work_item() -> dict[str, object]:
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": "tenant-p8-s84",
        "approval_work_item_id": "84000000-0000-4000-8000-000000000001",
        "approval_domain": "NSL_WRITE",
        "source_ref": "approval-request-p8-s84",
        "semantic_hash": "sha256:" + "8" * 64,
        "title": "Approve P8-S84 protected WRITE",
        "display_safe_summary": "Verify current OA authority before decision.",
        "approval_provider_type": "NSL",
        "approval_target_ref": "approval-request-p8-s84",
        "target_approver_ref": "approver-p8-s84",
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": "agent-execution-p8-s84",
        "executable_step_id": "step-p8-s84",
        "nsl_execution_id": "nsl-execution-p8-s84",
        "business_operation_id": "business-operation-p8-s84",
        "approval_request_id": "approval-request-p8-s84",
        "protected_request_ref": "ae-private:approval-request-p8-s84",
        "resume_target_ref": "ae-wait:approval-request-p8-s84",
        "state": "PENDING",
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "version": 1,
    }


def test_approval_authority_revoked_before_decision_has_zero_side_effects() -> None:
    repository = InMemoryApprovalWorkItemRepository()
    repository.insert(_approval_work_item())
    authorization = _RevocableApprovalAuthorization()
    service = ApprovalDecisionService(
        repository,
        authorizer=ApprovalDecisionAuthorizer(
            authorization,
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
    )

    authorization.revoke("approval:decide")
    with pytest.raises(ApprovalDecisionAuthorizationError) as denied:
        service.decide(
            tenant_id="tenant-p8-s84",
            approval_work_item_id="84000000-0000-4000-8000-000000000001",
            decision="APPROVE",
            decided_by="approver-p8-s84",
        )

    assert denied.value.status_code == 403
    assert denied.value.retryable is False
    assert authorization.calls == 1
    assert repository.get_decision(
        tenant_id="tenant-p8-s84",
        approval_work_item_id="84000000-0000-4000-8000-000000000001",
    ) is None
    assert repository.list_pending_approval_events(limit=10) == []
    assert repository.get(
        tenant_id="tenant-p8-s84",
        approval_work_item_id="84000000-0000-4000-8000-000000000001",
    )["state"] == "PENDING"


def test_finance_authority_revoked_before_mutation_has_zero_eos_rows() -> None:
    engine, factory = s58._factory()
    s58._seed(factory)
    authorization = s58.CurrentAuthorizationSource()
    authorization.allowed = True
    service = EosCreateVoucherDraftService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            factory,
            id_factory=lambda: "85000000-0000-4000-8000-000000000084",
            clock=lambda: NOW,
        ),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        authorizer=EosVoucherAuthorizationClient(authorization, clock=lambda: NOW),
        id_factory=lambda: "84000000-0000-4000-8000-000000000084",
        clock=lambda: NOW,
    )

    authorization.allowed = False
    with pytest.raises(EosVoucherCommandError) as denied:
        service.execute(
            s58._payload(),
            caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
        )

    assert denied.value.error_code == "EOS_AUTHORIZATION_DENIED"
    assert denied.value.status_code == 403
    assert authorization.calls == [False]
    assert all(count == 0 for count in s58._counts(factory).values())
    engine.dispose()


class _InactiveOaSessionClient:
    def __init__(self) -> None:
        self.introspection_calls = 0

    def introspect_session(self, *_args, **_kwargs):
        self.introspection_calls += 1
        return {"active": False, "inactive_reason": "revoked"}


class _UnexpectedAttachmentAccess:
    def __init__(self) -> None:
        self.calls = 0

    def __getattr__(self, _name: str):
        def unexpected(*_args, **_kwargs):
            self.calls += 1
            raise AssertionError("revoked sessions must not reach attachment storage")

        return unexpected


def test_revoked_oa_session_blocks_private_attachment_before_storage_access() -> None:
    session_client = _InactiveOaSessionClient()
    repository = _UnexpectedAttachmentAccess()
    gateway = _UnexpectedAttachmentAccess()
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_voucher_attachment_routes(
        app,
        repository=repository,
        gateway=gateway,
        oa_session_client=session_client,
        session_mode=AUTH_SESSION_MODE_OA,
    )

    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE_NAME, "revoked-session-p8-s84")
        response = client.get(
            "/api/v1/voucher-attachments/batches/"
            "84000000-0000-4000-8000-000000000002/items/"
            "84000000-0000-4000-8000-000000000003/content"
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "ae.oa_session_inactive"
    assert session_client.introspection_calls == 1
    assert repository.calls == 0
    assert gateway.calls == 0
