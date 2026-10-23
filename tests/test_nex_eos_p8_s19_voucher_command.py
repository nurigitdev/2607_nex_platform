from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosAuthorizationError,
    EosAuthorizationEvidence,
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherCommandError,
    InMemoryEosBusinessTransactionCoordinator,
    NvtProjectInput,
    ProjectInput,
    ResolvedObjectRef,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosAttachmentRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    create_eos_app,
    parse_create_voucher_draft_command,
    voucher_payload_hash,
)
from nex_runtime import issue_mock_service_token
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
NVT_ID = "81000000-0000-4000-8000-000000000001"
PROJECT_ID = "82000000-0000-4000-8000-000000000001"
DEBIT_ID = "83000000-0000-4000-8000-000000000001"
CREDIT_ID = "83000000-0000-4000-8000-000000000002"
VOUCHER_ID = "84000000-0000-4000-8000-000000000001"
ATTACHMENT_BATCH_ID = "85000000-0000-4000-8000-000000000010"
ATTACHMENT_MANIFEST_HASH = "sha256:" + "c" * 64
NOW = datetime(2026, 10, 21, 1, 2, 3, tzinfo=UTC)


class Authorizer:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def authorize_create(self, target):
        self.calls.append(target)
        if self.error:
            raise self.error
        return EosAuthorizationEvidence(
            tenant_id=target.tenant_id,
            subject_id=target.subject_id,
            service_subject=target.service_subject,
            required_scope="finance:voucher-draft:create",
            project_id=target.project_id,
            resource_type=target.resource_type,
            resource_id=target.resource_id,
            org_unit_id=None,
            authorization_revision_hash="a" * 64,
            authorization_checked_at=NOW,
        )


class Resolver:
    def __init__(self, *, error=None):
        self.error = error

    def resolve_object_ref(self, **kwargs):
        if self.error:
            raise self.error
        return ResolvedObjectRef(
            object_ref=kwargs["object_ref"],
            storage_owner="nex-ae-api",
            tenant_id=kwargs["tenant_id"],
            purpose="EOS_VOUCHER_ATTACHMENT",
            status="READY",
            content_sha256="b" * 64,
            size_bytes=10,
            media_type="application/pdf",
            authenticated=True,
            immutable=True,
            version_ref="version-1",
            attachment_id="85000000-0000-4000-8000-000000000001",
            attachment_batch_id=ATTACHMENT_BATCH_ID,
            attachment_manifest_hash=ATTACHMENT_MANIFEST_HASH,
        )


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(factory):
    projects = SqlAlchemyEosProjectRepository(factory)
    accounts = SqlAlchemyEosAccountRepository(factory)
    projects.create_nvt_project(NvtProjectInput("tenant-a", NVT_ID, "NVT-A", "NVT A"))
    projects.create_project(
        ProjectInput(
            "tenant-a", PROJECT_ID, "PROJECT-A", "Project A", nvt_project_id=NVT_ID
        )
    )
    accounts.create_account(
        AccountInput(
            "tenant-a",
            DEBIT_ID,
            "TRAVEL",
            "Travel",
            "EXPENSE",
            "GENERAL",
            date(2026, 1, 1),
        )
    )
    accounts.create_account(
        AccountInput(
            "tenant-a", CREDIT_ID, "CASH", "Cash", "ASSET", "GENERAL", date(2026, 1, 1)
        )
    )


def _payload(**overrides):
    value = json.loads(
        (
            ROOT
            / "contracts/examples/service/eos_create_voucher_draft_command.golden_a.json"
        ).read_text()
    )
    value.update(overrides)
    if value.get("attachments"):
        value.setdefault("attachment_batch_id", ATTACHMENT_BATCH_ID)
        value.setdefault("attachment_manifest_hash", ATTACHMENT_MANIFEST_HASH)
    value["payload_hash"] = voucher_payload_hash(value)
    return value


def _service(factory, *, authorizer=None, resolver=None, voucher_id=VOUCHER_ID):
    identifiers = iter(
        (
            "87000000-0000-4000-8000-000000000001",
            "88000000-0000-4000-8000-000000000001",
        )
    )
    return EosCreateVoucherDraftService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            factory, id_factory=lambda: next(identifiers), clock=lambda: NOW
        ),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        attachments=(
            SqlAlchemyEosAttachmentRepository(factory, resolver)
            if resolver is not None
            else None
        ),
        authorizer=authorizer or Authorizer(),
        id_factory=lambda: voucher_id,
        clock=lambda: NOW,
    )


def _caller():
    return EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def _count(factory, table):
    with factory() as session:
        return session.execute(select(func.count()).select_from(table)).scalar_one()


def test_command_commits_voucher_operation_idempotency_and_outbox_atomically(factory):
    _seed(factory)
    authorizer = Authorizer()
    service = _service(factory, authorizer=authorizer)
    payload = _payload()

    result = service.execute(payload, caller=_caller())
    replay = service.execute(payload, caller=_caller())

    assert result["idempotency_disposition"] == "CREATED"
    assert replay == {**result, "idempotency_disposition": "REPLAYED"}
    assert result["voucher_ref"]["id"] == VOUCHER_ID
    assert len(authorizer.calls) == 2
    assert authorizer.calls[0].subject_id == "employee-1001"
    for table in (
        EOS_VOUCHER_DRAFT_TABLE,
        EOS_BUSINESS_OPERATION_TABLE,
        EOS_IDEMPOTENCY_TABLE,
        EOS_OUTBOX_TABLE,
    ):
        assert _count(factory, table) == 1
    with factory() as session:
        stored = session.execute(select(EOS_BUSINESS_OPERATION_TABLE)).mappings().one()
    assert stored["result_json"]["authorization_revision_hash"] == "a" * 64
    assert stored["result_json"]["committed_at"] == "2026-10-21T01:02:03Z"


def test_payload_hash_and_authorization_fail_before_any_mutation(factory):
    _seed(factory)
    authorizer = Authorizer()
    payload = _payload()
    payload["description"] = "tampered"
    with pytest.raises(EosVoucherCommandError) as mismatch:
        _service(factory, authorizer=authorizer).execute(payload, caller=_caller())
    assert mismatch.value.error_code == "EOS_VOUCHER_PAYLOAD_HASH_MISMATCH"
    assert authorizer.calls == []

    denied_authorizer = Authorizer(
        error=EosAuthorizationError(
            "EOS_AUTHORIZATION_DENIED", "denied", status_code=403
        )
    )
    with pytest.raises(EosVoucherCommandError) as denied:
        _service(factory, authorizer=denied_authorizer).execute(
            _payload(), caller=_caller()
        )
    assert denied.value.status_code == 403
    assert _count(factory, EOS_BUSINESS_OPERATION_TABLE) == 0


def test_payload_hash_excludes_approval_control_lineage() -> None:
    first = _payload()
    second = _payload(
        nsl_approval_request_id="approval-request-2002",
        nsl_approval_evidence_ref="approval-evidence-2002",
        business_approval_proof_ref="business-approval-proof-2002",
    )

    assert first["payload_hash"] == second["payload_hash"]
    assert voucher_payload_hash(first) == voucher_payload_hash(second)
    assert first["nsl_approval_request_id"] != second["nsl_approval_request_id"]


def test_domain_failure_rolls_back_business_control_records(factory):
    _seed(factory)
    payload = _payload()
    payload["lines"][1]["signed_amount"] = "-9.00"
    payload["payload_hash"] = voucher_payload_hash(payload)
    with pytest.raises(EosVoucherCommandError) as error:
        _service(factory).execute(payload, caller=_caller())
    assert error.value.error_code == "EOS_VOUCHER_UNBALANCED"
    for table in (
        EOS_VOUCHER_DRAFT_TABLE,
        EOS_BUSINESS_OPERATION_TABLE,
        EOS_IDEMPOTENCY_TABLE,
        EOS_OUTBOX_TABLE,
    ):
        assert _count(factory, table) == 0


def test_attachment_resolution_and_failure_share_command_transaction(factory):
    _seed(factory)
    attachment = {
        "attachment_id": "85000000-0000-4000-8000-000000000001",
        "object_ref": "objref:ownerissuedopaque0001",
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": 10,
        "content_sha256": "b" * 64,
        "evidence_ref": "approval-evidence-1001",
    }
    result = _service(factory, resolver=Resolver()).execute(
        _payload(attachments=[attachment]), caller=_caller()
    )
    assert result["commit_state"] == "COMMITTED"
    assert _count(factory, EOS_VOUCHER_ATTACHMENT_TABLE) == 1


def test_attachment_resolver_failure_rolls_back_voucher_and_operation(factory):
    _seed(factory)
    attachment = {
        "attachment_id": "85000000-0000-4000-8000-000000000001",
        "object_ref": "objref:ownerissuedopaque0001",
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": 10,
        "content_sha256": "b" * 64,
    }
    with pytest.raises(EosVoucherCommandError) as error:
        _service(factory, resolver=Resolver(error=RuntimeError("offline"))).execute(
            _payload(attachments=[attachment]), caller=_caller()
        )
    assert error.value.error_code == "EOS_ATTACHMENT_RESOLVER_UNAVAILABLE"
    assert _count(factory, EOS_VOUCHER_DRAFT_TABLE) == 0
    assert _count(factory, EOS_BUSINESS_OPERATION_TABLE) == 0


def test_attachment_command_requires_configured_resolver(factory):
    _seed(factory)
    attachment = {
        "attachment_id": "85000000-0000-4000-8000-000000000001",
        "object_ref": "objref:ownerissuedopaque0001",
        "display_name": "receipt.pdf",
        "media_type": "application/pdf",
        "size_bytes": 10,
        "content_sha256": "b" * 64,
    }
    with pytest.raises(EosVoucherCommandError) as error:
        _service(factory).execute(_payload(attachments=[attachment]), caller=_caller())
    assert error.value.status_code == 503
    assert _count(factory, EOS_VOUCHER_DRAFT_TABLE) == 0


def test_same_idempotency_key_with_different_payload_is_conflict(factory):
    _seed(factory)
    service = _service(factory)
    service.execute(_payload(), caller=_caller())
    changed = _payload(description="different canonical payload")
    with pytest.raises(EosVoucherCommandError) as conflict:
        service.execute(changed, caller=_caller())
    assert conflict.value.status_code == 409
    assert _count(factory, EOS_VOUCHER_DRAFT_TABLE) == 1


def test_command_requires_sql_transaction_and_timezone_aware_clock(factory):
    _seed(factory)
    without_database_transaction = EosCreateVoucherDraftService(
        coordinator=InMemoryEosBusinessTransactionCoordinator(),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        authorizer=Authorizer(),
        id_factory=lambda: VOUCHER_ID,
        clock=lambda: NOW,
    )
    with pytest.raises(EosVoucherCommandError) as transaction_required:
        without_database_transaction.execute(_payload(), caller=_caller())
    assert transaction_required.value.error_code == "EOS_VOUCHER_TRANSACTION_REQUIRED"

    bad_clock = _service(factory)
    bad_clock._clock = lambda: datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(EosVoucherCommandError) as clock_error:
        bad_clock.execute(_payload(), caller=_caller())
    assert clock_error.value.error_code == "EOS_VOUCHER_CLOCK_INVALID"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda p: p.update(schema_version="v2"),
        lambda p: p.update(extra="not-allowed"),
        lambda p: p.update(lines=[]),
        lambda p: p.update(lines="bad"),
        lambda p: p["lines"][0].update(line_no=2),
        lambda p: p["lines"][0].update(signed_amount=10.0),
        lambda p: p["project_ref"].update(type="other.project"),
        lambda p: p.update(tenant_id="bad value"),
        lambda p: p.update(business_operation_id="bad"),
        lambda p: p.update(idempotency_key=" padded "),
        lambda p: p.update(voucher_type="bad"),
        lambda p: p.update(payload_hash="bad"),
        lambda p: p.update(transaction_date="bad-date"),
        lambda p: p.update(transaction_date=20261021),
        lambda p: p.update(trace={"trace_id": "only"}),
        lambda p: p.update(attachments="bad"),
        lambda p: p.update(attachments=[{}] * 21),
        lambda p: p["lines"][0].update(evidence_refs="bad"),
        lambda p: p["lines"][0].update(evidence_refs=[f"ref-{i}" for i in range(21)]),
        lambda p: p["lines"][0].update(evidence_refs=["same", "same"]),
        lambda p: p["lines"][0].update(account_ref="bad"),
    ),
)
def test_parser_rejects_noncanonical_command_shapes(mutate):
    payload = _payload()
    mutate(payload)
    with pytest.raises(EosVoucherCommandError):
        parse_create_voucher_draft_command(payload)


def test_parser_accepts_optional_business_approval_and_null_line_description():
    payload = _payload(business_approval_proof_ref="business-approval-1")
    payload["lines"][0].pop("description")
    payload["payload_hash"] = voucher_payload_hash(payload)
    parsed = parse_create_voucher_draft_command(payload)
    assert parsed.business_approval_proof_ref == "business-approval-1"
    assert parsed.lines[0].description is None


def test_parser_rejects_non_object_command():
    with pytest.raises(EosVoucherCommandError):
        parse_create_voucher_draft_command([])  # type: ignore[arg-type]


def test_route_enforces_service_trust_status_and_problem_mapping():
    class FakeService:
        def __init__(self):
            self.error = None

        def execute(self, payload, *, caller):
            if self.error:
                raise self.error
            assert caller.subject == "service:nex-ae-api"
            return {
                "idempotency_disposition": "CREATED",
                "tenant_id": payload["tenant_id"],
            }

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s19",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    fake = FakeService()
    app.state.eos_voucher_command_service = fake
    client = TestClient(app)
    path = "/internal/v1/finance/voucher-drafts"
    assert client.post(path, json={"tenant_id": "tenant-a"}).status_code == 401
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = client.post(
        path,
        json={"tenant_id": "tenant-a"},
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 201
    fake.error = EosVoucherCommandError("DENIED", "denied", status_code=403)
    response = client.post(
        path,
        json={"tenant_id": "tenant-a"},
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "DENIED"


def test_route_is_retryable_when_command_dependencies_are_absent():
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s19",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = TestClient(app).post(
        "/internal/v1/finance/voucher-drafts",
        json={},
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 503
    assert response.json()["retryable"] is True
