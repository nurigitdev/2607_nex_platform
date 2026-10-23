from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from nex_eos import (
    EosBusinessFormalWcAdapter,
    EosBusinessFormalWcError,
    HttpWcApprovalWorkItemClient,
    SqlAlchemyEosApprovalInstanceRepository,
    deterministic_business_formal_work_item_id,
)
from nex_eos.app import create_eos_app
from nex_wc.approvals import (
    ApprovalWorkItemService,
    InMemoryApprovalWorkItemRepository,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
TENANT = "tenant-a"
INSTANCE_ID = "72000000-0000-4000-8000-000000000001"
STAGE_ID = "72000000-0000-4000-8000-000000000002"
OPERATION_ID = "72000000-0000-4000-8000-000000000003"
ORG_ID = "72000000-0000-4000-8000-000000000004"
PROJECT_ID = "72000000-0000-4000-8000-000000000005"


def _instance(**overrides):
    values = {
        "schema_version": "eos_approval_instance.v1",
        "tenant_id": TENANT,
        "approval_instance_id": INSTANCE_ID,
        "idempotency_key": "p8-s71-instance",
        "policy_ref": {
            "approval_policy_id": "72000000-0000-4000-8000-000000000006",
            "version": 1,
            "policy_hash": "sha256:" + "1" * 64,
        },
        "approval_domain": "BUSINESS_FORMAL",
        "business_operation_id": OPERATION_ID,
        "operation": "CREATE_VOUCHER_DRAFT",
        "protected_operation_ref": "eos:business-operation:p8-s71",
        "payload_hash": "sha256:" + "2" * 64,
        "write_intent_hash": "sha256:" + "3" * 64,
        "requester_ref": {"type": "oa.user", "id": "employee-1001"},
        "org_unit_ref": {"type": "eos.org_unit", "id": ORG_ID},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "state": "PENDING",
        "active_stage_order": 1,
        "stage_count": 2,
        "version": 1,
        "expires_at": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "correlation_id": "p8-s71-correlation",
        "causation_id": "p8-s71-causation",
        "binding_hash": "sha256:" + "4" * 64,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
        "stages": [],
        "decision_history": [],
    }
    values.update(overrides)
    return values


def _stage(**overrides):
    values = {
        "schema_version": "eos_approval_stage.v1",
        "tenant_id": TENANT,
        "approval_stage_id": STAGE_ID,
        "approval_instance_id": INSTANCE_ID,
        "stage_order": 1,
        "policy_stage_order": 1,
        "position_type": "TEAM_LEAD",
        "quorum_count": 1,
        "separation_policy": "REQUESTER_EXCLUDED",
        "state": "ACTIVE",
        "version": 1,
        "activated_at": NOW.isoformat().replace("+00:00", "Z"),
        "decided_at": None,
    }
    values.update(overrides)
    return values


_DEFAULT = object()


class InstanceSource:
    def __init__(self, instance=_DEFAULT, stage=_DEFAULT):
        self.instance = _instance() if instance is _DEFAULT else instance
        self.stage = _stage() if stage is _DEFAULT else stage

    def get_instance(self, *, tenant_id, approval_instance_id):
        del tenant_id, approval_instance_id
        return self.instance

    def get_active_stage(self, *, tenant_id, approval_instance_id):
        del tenant_id, approval_instance_id
        return self.stage


class CapturingClient:
    def __init__(self, *, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.calls = []

    def create_or_get(self, work_item):
        self.calls.append(dict(work_item))
        if self.failure is not None:
            raise self.failure
        if self.response is not None:
            return self.response
        return {"work_item": dict(work_item), "created": True}


def _adapter(*, source=None, client=None, clock=lambda: NOW):
    return EosBusinessFormalWcAdapter(
        approval_instances=source or InstanceSource(),  # type: ignore[arg-type]
        wc_client=client or CapturingClient(),
        clock=clock,
    )


def test_projects_active_stage_to_existing_wc_contract_and_replays() -> None:
    repository = InMemoryApprovalWorkItemRepository()

    class RepositoryClient:
        def create_or_get(self, work_item):
            return ApprovalWorkItemService(repository).create_or_get(work_item)

    adapter = _adapter(client=RepositoryClient())
    first = adapter.project_active_stage(
        tenant_id=TENANT, approval_instance_id=INSTANCE_ID
    )
    replay = adapter.project_active_stage(
        tenant_id=TENANT, approval_instance_id=INSTANCE_ID
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert replay["work_item"] == first["work_item"]
    item = first["work_item"]
    assert item["approval_domain"] == "BUSINESS_FORMAL"
    assert item["approval_provider_type"] == "EOS"
    assert item["source_ref"] == f"eos.approval-stage:{STAGE_ID}"
    assert item["approval_work_item_id"] == deterministic_business_formal_work_item_id(
        tenant_id=TENANT, approval_stage_id=STAGE_ID
    )
    assert item["target_approver_ref"] is None
    assert item["target_role_ref"] == "TEAM_LEAD"
    assert item["target_org_scope_ref"] == ORG_ID
    assert item["target_project_scope_ref"] == PROJECT_ID
    assert item["business_operation_id"] == OPERATION_ID
    assert item["protected_request_ref"] == "eos:business-operation:p8-s71"
    assert item["semantic_hash"].startswith("sha256:")
    assert "1000" not in item["display_safe_summary"]


def test_work_item_identity_is_stage_scoped_and_deterministic() -> None:
    first = deterministic_business_formal_work_item_id(
        tenant_id=TENANT, approval_stage_id=STAGE_ID
    )
    assert first == deterministic_business_formal_work_item_id(
        tenant_id=TENANT, approval_stage_id=STAGE_ID
    )
    assert first != deterministic_business_formal_work_item_id(
        tenant_id=TENANT,
        approval_stage_id="72000000-0000-4000-8000-000000000099",
    )


def test_projection_without_expiry_remains_valid() -> None:
    result = _adapter(
        source=InstanceSource(instance=_instance(expires_at=None))
    ).project_active_stage(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)

    assert result["created"] is True
    assert result["work_item"]["expires_at"] is None


@pytest.mark.parametrize(
    ("source", "error_code"),
    (
        (InstanceSource(instance=None), "EOS_APPROVAL_INSTANCE_NOT_FOUND"),
        (
            InstanceSource(instance=_instance(state="APPROVED")),
            "EOS_APPROVAL_INSTANCE_NOT_PROJECTABLE",
        ),
        (
            InstanceSource(instance=_instance(approval_domain="NSL_WRITE")),
            "EOS_APPROVAL_INSTANCE_NOT_PROJECTABLE",
        ),
        (InstanceSource(stage=None), "EOS_APPROVAL_ACTIVE_STAGE_MISSING"),
        (
            InstanceSource(stage=_stage(state="WAITING")),
            "EOS_APPROVAL_ACTIVE_STAGE_MISMATCH",
        ),
        (
            InstanceSource(stage=_stage(stage_order=2)),
            "EOS_APPROVAL_ACTIVE_STAGE_MISMATCH",
        ),
        (
            InstanceSource(stage=_stage(tenant_id="tenant-b")),
            "EOS_APPROVAL_ACTIVE_STAGE_MISMATCH",
        ),
        (
            InstanceSource(
                stage=_stage(
                    approval_instance_id="72000000-0000-4000-8000-000000000099"
                )
            ),
            "EOS_APPROVAL_ACTIVE_STAGE_MISMATCH",
        ),
    ),
)
def test_non_projectable_instance_and_stage_fail_closed(source, error_code) -> None:
    with pytest.raises(EosBusinessFormalWcError) as error:
        _adapter(source=source).project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    ("expiry", "clock", "error_code"),
    (
        (
            (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
            lambda: NOW,
            "EOS_APPROVAL_INSTANCE_EXPIRED",
        ),
        ("not-a-time", lambda: NOW, "EOS_APPROVAL_INSTANCE_INVALID"),
        (123, lambda: NOW, "EOS_APPROVAL_INSTANCE_INVALID"),
        (
            None,
            lambda: NOW.replace(tzinfo=None),
            "EOS_BUSINESS_FORMAL_WC_CLOCK_INVALID",
        ),
    ),
)
def test_expiry_and_clock_fail_closed(expiry, clock, error_code) -> None:
    with pytest.raises(EosBusinessFormalWcError) as error:
        _adapter(
            source=InstanceSource(instance=_instance(expires_at=expiry)),
            clock=clock,
        ).project_active_stage(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    "response",
    (
        None,
        {},
        {"work_item": {}, "created": "yes"},
    ),
)
def test_invalid_wc_response_shape_is_denied(response) -> None:
    client = CapturingClient(response=response)
    if response is None:
        client.response = []
    with pytest.raises(EosBusinessFormalWcError) as error:
        _adapter(client=client).project_active_stage(
            tenant_id=TENANT, approval_instance_id=INSTANCE_ID
        )
    assert error.value.error_code == "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID"


def test_wc_response_lineage_mismatch_and_untyped_failure_are_redacted() -> None:
    expected = CapturingClient()
    _adapter(client=expected).project_active_stage(
        tenant_id=TENANT, approval_instance_id=INSTANCE_ID
    )
    changed = dict(expected.calls[0])
    changed["semantic_hash"] = "sha256:" + "9" * 64
    with pytest.raises(EosBusinessFormalWcError) as mismatch:
        _adapter(
            client=CapturingClient(response={"work_item": changed, "created": False})
        ).project_active_stage(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    assert mismatch.value.error_code == "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID"

    with pytest.raises(EosBusinessFormalWcError) as unavailable:
        _adapter(
            client=CapturingClient(failure=RuntimeError("private failure"))
        ).project_active_stage(tenant_id=TENANT, approval_instance_id=INSTANCE_ID)
    assert unavailable.value.error_code == "EOS_BUSINESS_FORMAL_WC_UNAVAILABLE"
    assert "private failure" not in unavailable.value.detail


class FakeResponse:
    def __init__(self, status_code, payload=None, failure=None):
        self.status_code = status_code
        self.payload = payload
        self.failure = failure

    def json(self):
        if self.failure is not None:
            raise self.failure
        return self.payload


def test_http_wc_client_sends_service_boundary_headers(monkeypatch) -> None:
    captured = {}
    work_item = {"tenant_id": TENANT, "approval_work_item_id": "item-1"}
    payload = {"work_item": work_item, "created": True}

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse(201, payload)

    monkeypatch.setattr(httpx, "post", post)
    result = HttpWcApprovalWorkItemClient(
        base_url="http://wc.local/", service_token=" token ", timeout_seconds=23
    ).create_or_get(work_item)

    assert result == payload
    assert captured["url"] == "http://wc.local/api/v1/approval-work-items"
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert captured["headers"]["X-NeX-Tenant-Id"] == TENANT
    assert captured["headers"]["X-Service-ID"] == "nex-eos"
    assert captured["timeout"] == 23


def test_http_wc_client_failure_mapping(monkeypatch) -> None:
    client = HttpWcApprovalWorkItemClient(service_token="")
    with pytest.raises(EosBusinessFormalWcError) as missing:
        client.create_or_get({"tenant_id": TENANT})
    assert missing.value.retryable is True

    def network_failure(*_args, **_kwargs):
        raise httpx.ConnectError("private network detail")

    monkeypatch.setattr(httpx, "post", network_failure)
    with pytest.raises(EosBusinessFormalWcError) as network:
        HttpWcApprovalWorkItemClient(service_token="token").create_or_get(
            {"tenant_id": TENANT}
        )
    assert network.value.error_code == "EOS_BUSINESS_FORMAL_WC_UNAVAILABLE"
    assert "private network detail" not in network.value.detail


@pytest.mark.parametrize(
    ("response", "error_code", "retryable"),
    (
        (
            FakeResponse(
                200,
                failure=json.JSONDecodeError("bad", "x", 0),
            ),
            "EOS_BUSINESS_FORMAL_WC_RESPONSE_INVALID",
            False,
        ),
        (
            FakeResponse(409, {"retryable": False}),
            "EOS_BUSINESS_FORMAL_WC_REJECTED",
            False,
        ),
        (
            FakeResponse(503, {"retryable": True}),
            "EOS_BUSINESS_FORMAL_WC_REJECTED",
            True,
        ),
        (
            FakeResponse(500, "upstream-error"),
            "EOS_BUSINESS_FORMAL_WC_REJECTED",
            True,
        ),
        (
            FakeResponse(409, {"retryable": True}),
            "EOS_BUSINESS_FORMAL_WC_REJECTED",
            True,
        ),
    ),
)
def test_http_wc_client_rejects_invalid_or_error_responses(
    monkeypatch, response, error_code, retryable
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: response)
    with pytest.raises(EosBusinessFormalWcError) as error:
        HttpWcApprovalWorkItemClient(service_token="token").create_or_get(
            {"tenant_id": TENANT}
        )
    assert error.value.error_code == error_code
    assert error.value.retryable is retryable


def test_app_wires_wc_adapter_only_with_database_and_service_trust(monkeypatch) -> None:
    base = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s71",
        "NEX_BUILD_SHA": "p8s71test",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    assert create_eos_app(environ=base).state.eos_business_formal_wc_adapter is None

    engine = create_engine("sqlite+pysqlite:///:memory:")
    from nex_eos import dependencies

    runtime = SimpleNamespace(session_factory=sessionmaker(bind=engine))
    monkeypatch.setattr(
        dependencies, "build_eos_database_runtime", lambda **_kwargs: runtime
    )
    without_token = create_eos_app(
        environ={**base, "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:"}
    )
    assert without_token.state.eos_business_formal_wc_adapter is None

    with_token = create_eos_app(
        environ={
            **base,
            "NEX_EOS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "NEX_EOS_TO_WC_SERVICE_TOKEN": "test-token",
            "NEX_WC_BASE_URL": "http://wc.test",
        }
    )
    assert isinstance(
        with_token.state.eos_business_formal_wc_adapter,
        EosBusinessFormalWcAdapter,
    )
    assert isinstance(
        with_token.state.eos_approval_instances,
        SqlAlchemyEosApprovalInstanceRepository,
    )
