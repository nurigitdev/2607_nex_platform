from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest
from nex_eos import (
    EOS_METADATA,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    AeAttachmentResolutionError,
    EosAuthorizationEvidence,
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherCommandError,
    HttpAeVoucherAttachmentResolver,
    NvtProjectInput,
    ProjectInput,
    ResolvedObjectRef,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosAttachmentRepository,
    SqlAlchemyEosBusinessOperationQuery,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    SqlAlchemyEosVoucherVerificationQuery,
    voucher_payload_hash,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p8-s75f"
PROJECT_ID = "75f00000-0000-4000-8000-000000000001"
NVT_ID = "75f00000-0000-4000-8000-000000000002"
DEBIT_ID = "75f00000-0000-4000-8000-000000000003"
CREDIT_ID = "75f00000-0000-4000-8000-000000000004"
OPERATION_ID = "75f00000-0000-4000-8000-000000000005"
VOUCHER_ID = "75f00000-0000-4000-8000-000000000006"
BATCH_ID = "75f00000-0000-4000-8000-000000000007"
ATTACHMENT_ID = "75f00000-0000-4000-8000-000000000008"
MANIFEST_HASH = "sha256:" + "a" * 64
CONTENT_HASH = "b" * 64
OBJECT_REF = "objref:ae:voucher:p8s75f001"
NOW = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)


class _Authorizer:
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
            authorization_revision_hash="c" * 64,
            authorization_checked_at=NOW,
        )


class _Resolver:
    def __init__(self, **changes: object) -> None:
        self.changes = changes
        self.calls = 0

    def resolve_object_ref(self, **kwargs):
        self.calls += 1
        values = {
            "object_ref": kwargs["object_ref"],
            "storage_owner": "nex-ae-api",
            "tenant_id": kwargs["tenant_id"],
            "purpose": kwargs["required_purpose"],
            "status": "READY",
            "content_sha256": CONTENT_HASH,
            "size_bytes": 12,
            "media_type": "application/pdf",
            "authenticated": True,
            "immutable": True,
            "version_ref": "rustfs-version-1",
            "attachment_id": ATTACHMENT_ID,
            "attachment_batch_id": BATCH_ID,
            "attachment_manifest_hash": MANIFEST_HASH,
        }
        values.update(self.changes)
        return ResolvedObjectRef(**values)


@pytest.fixture
def boundary():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    projects = SqlAlchemyEosProjectRepository(factory)
    accounts = SqlAlchemyEosAccountRepository(factory)
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-75F", "NVT 75F"))
    projects.create_project(
        ProjectInput(
            TENANT, PROJECT_ID, "PROJECT-75F", "Project 75F", nvt_project_id=NVT_ID
        )
    )
    accounts.create_account(
        AccountInput(
            TENANT,
            DEBIT_ID,
            "TRAVEL-75F",
            "Travel",
            "EXPENSE",
            "GENERAL",
            date(2026, 1, 1),
        )
    )
    accounts.create_account(
        AccountInput(
            TENANT, CREDIT_ID, "CASH-75F", "Cash", "ASSET", "GENERAL", date(2026, 1, 1)
        )
    )
    yield factory
    engine.dispose()


def _payload(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": TENANT,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "p8-s75f-exactly-once",
        "payload_hash": "sha256:" + "0" * 64,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s75f"},
        "project_ref": {"type": "eos.project", "id": PROJECT_ID},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-23",
        "currency": "KRW",
        "description": "P8-S75F attachment admission",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": DEBIT_ID},
                "signed_amount": "12000.00",
                "economic_category": "TRAVEL",
                "description": "Receipt",
                "evidence_refs": ["approval-evidence-p8-s75f"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": CREDIT_ID},
                "signed_amount": "-12000.00",
                "economic_category": "CASH",
                "description": "Offset",
                "evidence_refs": ["approval-evidence-p8-s75f"],
            },
        ],
        "nsl_approval_request_id": "approval-request-p8-s75f",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s75f",
        "business_approval_proof_ref": None,
        "attachment_batch_id": BATCH_ID,
        "attachment_manifest_hash": MANIFEST_HASH,
        "attachments": [
            {
                "attachment_id": ATTACHMENT_ID,
                "object_ref": OBJECT_REF,
                "display_name": "receipt.pdf",
                "media_type": "application/pdf",
                "size_bytes": 12,
                "content_sha256": CONTENT_HASH,
                "evidence_ref": "approval-evidence-p8-s75f",
            }
        ],
        "trace": {
            "trace_id": "trace-p8-s75f",
            "correlation_id": "correlation-p8-s75f",
            "causation_id": "write-p8-s75f",
        },
    }
    value.update(changes)
    value["payload_hash"] = voucher_payload_hash(value)
    return value


def _service(factory, resolver):
    ids = iter(
        (
            "75f00000-0000-4000-8000-000000000009",
            "75f00000-0000-4000-8000-000000000010",
        )
    )
    return EosCreateVoucherDraftService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            factory, id_factory=lambda: next(ids), clock=lambda: NOW
        ),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        attachments=SqlAlchemyEosAttachmentRepository(factory, resolver),
        authorizer=_Authorizer(),
        id_factory=lambda: VOUCHER_ID,
        clock=lambda: NOW,
    )


def _caller() -> EosServiceCaller:
    return EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def test_exact_manifest_commits_atomically_replays_and_projects_identity(
    boundary,
) -> None:
    resolver = _Resolver()
    service = _service(boundary, resolver)
    created = service.execute(_payload(), caller=_caller())
    replayed = service.execute(_payload(), caller=_caller())

    assert created["idempotency_disposition"] == "CREATED"
    assert replayed["idempotency_disposition"] == "REPLAYED"
    assert resolver.calls == 1
    with boundary() as session:
        voucher = session.execute(select(EOS_VOUCHER_DRAFT_TABLE)).mappings().one()
        assert str(voucher["attachment_batch_id"]) == BATCH_ID
        assert voucher["attachment_manifest_hash"] == MANIFEST_HASH
        assert (
            session.execute(
                select(func.count()).select_from(EOS_VOUCHER_ATTACHMENT_TABLE)
            ).scalar_one()
            == 1
        )

    verified = SqlAlchemyEosVoucherVerificationQuery(boundary).verify(
        tenant_id=TENANT,
        voucher_id=VOUCHER_ID,
        business_operation_id=OPERATION_ID,
    )
    reconciled = SqlAlchemyEosBusinessOperationQuery(boundary).get(
        tenant_id=TENANT,
        business_operation_id=OPERATION_ID,
    )
    for projection in (verified, reconciled):
        assert projection["attachment_batch_id"] == BATCH_ID
        assert projection["attachment_manifest_hash"] == MANIFEST_HASH
        assert projection["attachment_ids"] == [ATTACHMENT_ID]


@pytest.mark.parametrize(
    "changes",
    (
        {"tenant_id": "tenant-other"},
        {"object_ref": "objref:ae:voucher:substituted01"},
        {"attachment_id": "75f00000-0000-4000-8000-000000000099"},
        {"attachment_batch_id": "75f00000-0000-4000-8000-000000000099"},
        {"attachment_manifest_hash": "sha256:" + "f" * 64},
        {"content_sha256": "f" * 64},
        {"authenticated": False},
        {"immutable": False},
    ),
)
def test_substitution_and_cross_tenant_resolution_leave_zero_mutation(
    boundary, changes
) -> None:
    with pytest.raises(EosVoucherCommandError) as error:
        _service(boundary, _Resolver(**changes)).execute(_payload(), caller=_caller())
    assert error.value.error_code == "EOS_ATTACHMENT_OBJECT_REJECTED"
    with boundary() as session:
        assert (
            session.execute(
                select(func.count()).select_from(EOS_VOUCHER_DRAFT_TABLE)
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                select(func.count()).select_from(EOS_VOUCHER_ATTACHMENT_TABLE)
            ).scalar_one()
            == 0
        )


def test_attachment_omission_of_manifest_lineage_fails_before_mutation(
    boundary,
) -> None:
    payload = _payload()
    payload.pop("attachment_batch_id")
    payload.pop("attachment_manifest_hash")
    with pytest.raises(EosVoucherCommandError) as error:
        _service(boundary, _Resolver()).execute(payload, caller=_caller())
    assert error.value.status_code == 422


def test_http_ae_resolver_uses_service_auth_and_closed_response_shape() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(
            method=request.method, headers=dict(request.headers), json=request.read()
        )
        return httpx.Response(
            200,
            json={
                "schema_version": "ae_voucher_attachment_resolution.v1",
                "tenant_id": TENANT,
                "attachment_batch_id": BATCH_ID,
                "attachment_id": ATTACHMENT_ID,
                "attachment_manifest_hash": MANIFEST_HASH,
                "object_ref": OBJECT_REF,
                "storage_owner": "nex-ae-api",
                "purpose": "EOS_VOUCHER_ATTACHMENT",
                "status": "READY",
                "content_sha256": CONTENT_HASH,
                "size_bytes": 12,
                "media_type": "application/pdf",
                "authenticated": True,
                "immutable": True,
                "object_version_ref": "rustfs-version-1",
                "resolved_at": "2026-10-23T18:00:00Z",
            },
            request=request,
        )

    resolver = HttpAeVoucherAttachmentResolver(
        "http://ae.test",
        "service-token",
        transport=httpx.MockTransport(handler),
    )
    result = resolver.resolve_object_ref(
        requester_service="nex-eos",
        tenant_id=TENANT,
        object_ref=OBJECT_REF,
        required_purpose="EOS_VOUCHER_ATTACHMENT",
    )
    assert result.attachment_manifest_hash == MANIFEST_HASH
    assert observed["method"] == "POST"
    assert observed["headers"]["authorization"] == "Bearer service-token"
    assert observed["headers"]["x-nex-tenant-id"] == TENANT


@pytest.mark.parametrize(
    "handler",
    (
        lambda request: httpx.Response(403, json={}, request=request),
        lambda request: httpx.Response(200, json={"extra": True}, request=request),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline")),
    ),
)
def test_http_ae_resolver_fails_closed(handler) -> None:
    resolver = HttpAeVoucherAttachmentResolver(
        "http://ae.test",
        "service-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AeAttachmentResolutionError):
        resolver.resolve_object_ref(
            requester_service="nex-eos",
            tenant_id=TENANT,
            object_ref=OBJECT_REF,
            required_purpose="EOS_VOUCHER_ATTACHMENT",
        )


def test_http_ae_resolver_rejects_invalid_configuration_and_caller() -> None:
    with pytest.raises(ValueError):
        HttpAeVoucherAttachmentResolver("file:///tmp/private", "token")
    with pytest.raises(ValueError):
        HttpAeVoucherAttachmentResolver("http://ae.test", " token")
    with pytest.raises(ValueError):
        HttpAeVoucherAttachmentResolver("http://ae.test", "token", timeout_seconds=0)
    resolver = HttpAeVoucherAttachmentResolver("http://ae.test", "token")
    with pytest.raises(AeAttachmentResolutionError):
        resolver.resolve_object_ref(
            requester_service="nex-cx",
            tenant_id=TENANT,
            object_ref=OBJECT_REF,
            required_purpose="EOS_VOUCHER_ATTACHMENT",
        )
