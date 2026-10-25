from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_METADATA,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_VOUCHER_AUDIT_SCOPE,
    EOS_VOUCHER_READ_SCOPE,
    AccountInput,
    EosAuthorizationEvidence,
    EosCreateVoucherDraftService,
    EosVoucherAccessError,
    EosVoucherAccessService,
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    VoucherDraftInput,
    VoucherLineInput,
    create_eos_app,
    voucher_payload_hash,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.voucher_access import _wire_value
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
TENANT = "tenant-s101"
PROJECT = "a1010000-0000-4000-8000-000000000001"
NVT = "a1010000-0000-4000-8000-000000000002"
MEMBERSHIP = "a1010000-0000-4000-8000-000000000003"
VOUCHER = "a1010000-0000-4000-8000-000000000004"
DEBIT = "a1010000-0000-4000-8000-000000000005"
CREDIT = "a1010000-0000-4000-8000-000000000006"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.scopes = {EOS_VOUCHER_READ_SCOPE}
        self.project_ids = None
        self.failure = None
        self.revision_hash = "a" * 64

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.failure is not None:
            raise self.failure
        value = {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes),
            "revision_hash": self.revision_hash,
        }
        if self.project_ids is not None:
            value["project_ids"] = self.project_ids
        return value


@pytest.fixture
def access_runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT, "NVT-S101", "NVT S101"))
    projects.create_project(
        ProjectInput(
            TENANT, PROJECT, "PROJECT-S101", "Project S101", nvt_project_id=NVT
        )
    )
    SqlAlchemyEosProjectMembershipRepository(factory).create_membership(
        ProjectMembershipInput(
            TENANT,
            MEMBERSHIP,
            PROJECT,
            "employee-1001",
            "MEMBER",
            "owner-1000",
            valid_from=NOW,
        )
    )
    accounts = SqlAlchemyEosAccountRepository(factory)
    accounts.create_account(
        AccountInput(
            TENANT, DEBIT, "TRAVEL", "Travel", "EXPENSE", "GENERAL", date(2026, 1, 1)
        )
    )
    accounts.create_account(
        AccountInput(
            TENANT, CREDIT, "CASH", "Cash", "ASSET", "GENERAL", date(2026, 1, 1)
        )
    )
    SqlAlchemyEosVoucherRepository(factory).create_draft(
        VoucherDraftInput(
            tenant_id=TENANT,
            voucher_id=VOUCHER,
            project_id=PROJECT,
            transaction_date=date(2026, 10, 25),
            description="Project travel expense",
            requester_ref={"type": "oa.user", "id": "employee-1001"},
            source_ref={"type": "nsl.approval_request", "id": "approval-s101"},
            lines=(
                VoucherLineInput(DEBIT, Decimal("10.00"), "TRAVEL"),
                VoucherLineInput(CREDIT, Decimal("-10.00"), "CASH"),
            ),
        )
    )
    source = AuthorizationSource()
    return (
        engine,
        factory,
        source,
        EosVoucherAccessService(
            session_factory=factory,
            authorization_source=source,
        ),
    )


def test_get_and_list_are_membership_filtered_and_deterministic(access_runtime) -> None:
    _engine, factory, _source, service = access_runtime

    with factory() as session:
        assert (
            service.require_create_membership(
                session,
                tenant_id=TENANT,
                project_id=PROJECT,
                subject_id="employee-1001",
            )
            == "MEMBER"
        )

    detail = service.get_draft(
        tenant_id=TENANT,
        voucher_id=VOUCHER,
        requester_subject_id="employee-1001",
    )
    collection = service.list_drafts(
        tenant_id=TENANT,
        project_id=PROJECT,
        requester_subject_id="employee-1001",
        limit=10,
        offset=0,
    )

    assert detail["operation_id"] == "FINANCE.VOUCHER_DRAFT.GET"
    assert detail["voucher"]["voucher_id"] == VOUCHER
    assert [line["signed_amount"] for line in detail["voucher"]["lines"]] == [
        "10.00",
        "-10.00",
    ]
    assert collection["operation_id"] == "FINANCE.VOUCHER_DRAFT.LIST"
    assert [item["voucher_id"] for item in collection["items"]] == [VOUCHER]
    assert collection["authorization_revision_hash"] == "a" * 64


def test_membership_and_oa_authority_are_independent_guards(access_runtime) -> None:
    _engine, factory, source, service = access_runtime
    with pytest.raises(EosVoucherAccessError) as outsider:
        service.get_draft(
            tenant_id=TENANT,
            voucher_id=VOUCHER,
            requester_subject_id="outsider",
        )
    assert outsider.value.error_code == "EOS_VOUCHER_NOT_FOUND"

    source.scopes.clear()
    with pytest.raises(EosVoucherAccessError) as no_scope:
        service.list_drafts(
            tenant_id=TENANT,
            project_id=PROJECT,
            requester_subject_id="employee-1001",
        )
    assert no_scope.value.error_code == "EOS_VOUCHER_AUTHORIZATION_DENIED"

    source.scopes.update({EOS_VOUCHER_READ_SCOPE, EOS_VOUCHER_AUDIT_SCOPE})
    audited = service.get_draft(
        tenant_id=TENANT,
        voucher_id=VOUCHER,
        requester_subject_id="finance-auditor",
    )
    assert audited["voucher"]["project_id"] == PROJECT

    source.project_ids = ["a1010000-0000-4000-8000-000000000099"]
    with pytest.raises(EosVoucherAccessError) as project_scope:
        service.list_drafts(
            tenant_id=TENANT,
            project_id=PROJECT,
            requester_subject_id="finance-auditor",
        )
    assert project_scope.value.status_code == 403

    source.project_ids = None
    with factory() as session:
        session.execute(
            update(EOS_PROJECT_MEMBER_TABLE)
            .where(EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT)
            .values(status="REMOVED", valid_to=NOW, removed_by_subject_id="owner-1000")
        )
        session.commit()
        with pytest.raises(EosVoucherAccessError) as removed:
            service.require_create_membership(
                session,
                tenant_id=TENANT,
                project_id=PROJECT,
                subject_id="employee-1001",
            )
    assert removed.value.error_code == "EOS_VOUCHER_PROJECT_MEMBERSHIP_REQUIRED"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("tenant_id", " "),
        ("voucher_id", "not-a-uuid"),
        ("limit", 0),
        ("limit", 101),
        ("offset", -1),
    ),
)
def test_invalid_query_inputs_fail_closed(access_runtime, field: str, value) -> None:
    _engine, _factory, _source, service = access_runtime
    with pytest.raises(EosVoucherAccessError) as raised:
        if field in {"tenant_id", "voucher_id"}:
            service.get_draft(
                tenant_id=value if field == "tenant_id" else TENANT,
                voucher_id=value if field == "voucher_id" else VOUCHER,
                requester_subject_id="employee-1001",
            )
        else:
            service.list_drafts(
                tenant_id=TENANT,
                project_id=PROJECT,
                requester_subject_id="employee-1001",
                **{field: value},
            )
    assert raised.value.error_code == "EOS_VOUCHER_ACCESS_INVALID"


def test_malformed_denied_and_unavailable_oa_evidence_fail_closed(
    access_runtime,
) -> None:
    _engine, _factory, source, service = access_runtime
    for mutation in ("inactive", "bad_revision", "bad_scopes"):
        source.active = mutation != "inactive"
        source.revision_hash = "bad" if mutation == "bad_revision" else "a" * 64
        source.scopes = "bad" if mutation == "bad_scopes" else {EOS_VOUCHER_READ_SCOPE}
        with pytest.raises(EosVoucherAccessError) as denied:
            service.get_draft(
                tenant_id=TENANT,
                voucher_id=VOUCHER,
                requester_subject_id="employee-1001",
            )
        assert denied.value.error_code == "EOS_VOUCHER_AUTHORIZATION_DENIED"

    source.active = True
    source.revision_hash = "a" * 64
    source.scopes = {EOS_VOUCHER_READ_SCOPE}
    for malformed_project_ids in ("not-a-sequence", [PROJECT, ""]):
        source.project_ids = malformed_project_ids
        with pytest.raises(EosVoucherAccessError) as malformed_scope:
            service.list_drafts(
                tenant_id=TENANT,
                project_id=PROJECT,
                requester_subject_id="employee-1001",
            )
        assert malformed_scope.value.error_code == "EOS_VOUCHER_AUTHORIZATION_DENIED"

    source.project_ids = None
    source.scopes = {EOS_VOUCHER_READ_SCOPE}
    source.failure = AuthorizationSubjectDenied("inactive")
    with pytest.raises(EosVoucherAccessError) as typed_denial:
        service.get_draft(
            tenant_id=TENANT,
            voucher_id=VOUCHER,
            requester_subject_id="employee-1001",
        )
    assert typed_denial.value.status_code == 403

    source.failure = RuntimeError("private OA outage")
    with pytest.raises(EosVoucherAccessError) as unavailable:
        service.list_drafts(
            tenant_id=TENANT,
            project_id=PROJECT,
            requester_subject_id="employee-1001",
        )
    assert unavailable.value.retryable is True


def test_timezone_aware_wire_timestamp_is_normalized_to_utc() -> None:
    assert _wire_value(NOW) == "2026-10-25T12:00:00Z"


def test_query_persistence_errors_are_typed(access_runtime) -> None:
    _engine, _factory, _source, _service = access_runtime

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement):
            raise SQLAlchemyError("private database failure")

    broken = EosVoucherAccessService(
        session_factory=lambda: BrokenSession(),  # type: ignore[arg-type]
        authorization_source=AuthorizationSource(),
    )
    for operation in (
        lambda: broken.get_draft(
            tenant_id=TENANT,
            voucher_id=VOUCHER,
            requester_subject_id="employee-1001",
        ),
        lambda: broken.list_drafts(
            tenant_id=TENANT,
            project_id=PROJECT,
            requester_subject_id="employee-1001",
        ),
    ):
        with pytest.raises(EosVoucherAccessError) as unavailable:
            operation()
        assert unavailable.value.error_code == "EOS_VOUCHER_QUERY_UNAVAILABLE"


def test_create_service_invokes_project_membership_guard_before_mutation() -> None:
    payload = json.loads(
        (
            ROOT
            / "contracts/examples/service/eos_create_voucher_draft_command.golden_a.json"
        ).read_text()
    )
    payload["payload_hash"] = voucher_payload_hash(payload)

    class Coordinator:
        def execute(self, request, mutation):
            result = mutation(object())
            return SimpleNamespace(
                tenant_id=request.tenant_id,
                business_operation_id=request.business_operation_id,
                idempotency_key=request.idempotency_key,
                payload_hash=request.payload_hash,
                commit_state="COMMITTED",
                created=True,
                result=result,
                event_id="a1010000-0000-4000-8000-000000000099",
            )

    class Authorizer:
        def authorize_create(self, target):
            return EosAuthorizationEvidence(
                tenant_id=target.tenant_id,
                subject_id=target.subject_id,
                service_subject=target.service_subject,
                required_scope="finance:voucher-draft:create",
                project_id=target.project_id,
                resource_type=target.resource_type,
                resource_id=target.resource_id,
                org_unit_id=None,
                authorization_revision_hash="b" * 64,
                authorization_checked_at=NOW,
            )

    calls = []

    class Guard:
        def require_create_membership(self, session, **kwargs):
            calls.append((session, kwargs))
            return "MEMBER"

    class Vouchers:
        def create_draft_in_session(self, session, value):
            assert calls and calls[0][0] is session
            return {"voucher_id": value.voucher_id}

    result = EosCreateVoucherDraftService(
        coordinator=Coordinator(),
        vouchers=Vouchers(),
        authorizer=Authorizer(),
        project_access=Guard(),
        id_factory=lambda: VOUCHER,
        clock=lambda: NOW,
    ).execute(
        payload,
        caller=SimpleNamespace(
            subject="nex-ae-api",
            audience="nex-eos",
            scopes=("service:call",),
        ),
    )

    assert result["voucher_ref"]["id"] == VOUCHER
    assert calls[0][1]["subject_id"] == payload["requester_ref"]["id"]


def test_routes_require_service_trust_and_preserve_canonical_operation_ids() -> None:
    class FakeAccess:
        def get_draft(self, **kwargs):
            return {"operation_id": "FINANCE.VOUCHER_DRAFT.GET", **kwargs}

        def list_drafts(self, **kwargs):
            return {"operation_id": "FINANCE.VOUCHER_DRAFT.LIST", **kwargs}

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s101",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_voucher_access_service = FakeAccess()
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
    }

    assert (
        client.get(
            f"/internal/v1/finance/voucher-drafts/{VOUCHER}",
            params={"requester_subject_id": "employee-1001"},
            headers={"X-NeX-Tenant-Id": TENANT},
        ).status_code
        == 401
    )
    detail = client.get(
        f"/internal/v1/finance/voucher-drafts/{VOUCHER}",
        params={"requester_subject_id": "employee-1001"},
        headers=headers,
    )
    collection = client.get(
        "/internal/v1/finance/voucher-drafts",
        params={
            "project_id": PROJECT,
            "requester_subject_id": "employee-1001",
        },
        headers=headers,
    )
    assert detail.json()["operation_id"] == "FINANCE.VOUCHER_DRAFT.GET"
    assert collection.json()["operation_id"] == "FINANCE.VOUCHER_DRAFT.LIST"
    operation_ids = {
        route.operation_id for route in app.routes if hasattr(route, "operation_id")
    }
    assert {"FINANCE.VOUCHER_DRAFT.GET", "FINANCE.VOUCHER_DRAFT.LIST"} <= operation_ids
