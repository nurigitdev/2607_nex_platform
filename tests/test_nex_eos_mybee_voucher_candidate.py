from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_APPROVAL_POLICY_TABLE,
    EOS_APPROVED_DOCUMENT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE,
    EOS_METADATA,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    EOS_VOUCHER_CANDIDATE_LINE_TABLE,
    EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
    EOS_VOUCHER_CANDIDATE_TABLE,
    AccountInput,
    EosCreateVoucherCandidateService,
    EosServiceCaller,
    EosVoucherAuthorizationClient,
    EosVoucherCandidateCommandError,
    EosVoucherCandidateError,
    LegalEntityInput,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherCandidateRepository,
    VoucherCandidateInput,
    finance_v2_api,
    parse_create_voucher_candidate_command,
    voucher_candidate_payload_hash,
    voucher_candidates,
)
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, func, make_url, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 12, 2, 0, tzinfo=UTC)
TENANT = "VO00"
COMPANY_ID = "32000000-0000-4000-8000-000000000001"
NVT_ID = "32000000-0000-4000-8000-000000000002"
PROJECT_ID = "32000000-0000-4000-8000-000000000003"
PROJECT_CODE = "VO00D260001"
ENVELOPE_ID = "32000000-0000-4000-8000-000000000004"
DOCUMENT_OPERATION_ID = "32000000-0000-4000-8000-000000000005"
POLICY_ID = "32000000-0000-4000-8000-000000000006"
DEBIT_ID = "32000000-0000-4000-8000-000000000007"
CREDIT_ID = "32000000-0000-4000-8000-000000000008"
BUSINESS_OPERATION_ID = "32000000-0000-4000-8000-000000000009"
CANDIDATE_ID = "32000000-0000-4000-8000-000000000010"
REVISION_ID = "32000000-0000-4000-8000-000000000011"
CASE_ID = "32000000-0000-4000-8000-000000000012"
EVIDENCE_ID = "32000000-0000-4000-8000-000000000013"
DOCUMENT_HASH = "sha256:" + "a" * 64
ATTACHMENT_HASH = "sha256:" + "b" * 64
PROOF_HASH = "sha256:" + "c" * 64
POLICY_HASH = "sha256:" + "d" * 64
PAYLOAD_HASH = "sha256:" + "e" * 64
EVIDENCE_HASH = "sha256:" + "f" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S3_01_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.scopes = ["finance:voucher-candidate:create"]

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": list(self.scopes),
            "project_ids": [PROJECT_ID],
            "revision_hash": "1" * 64,
        }


def _engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _seed(
    sessions,
    *,
    project_origin: str = "APPROVED_APPLICATION",
    project_status: str = "ACTIVE",
    document_state: str = "ACTIVE",
    allowed_project_codes: tuple[str, ...] = (PROJECT_CODE,),
) -> None:
    SqlAlchemyEosLegalEntityRepository(sessions).create_legal_entity(
        LegalEntityInput(
            TENANT,
            COMPANY_ID,
            "NURI",
            "Nuri Company",
            "KRW",
            "KRW",
            "Asia/Seoul",
            date(2026, 1, 1),
        )
    )
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-W30", "W30"))
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            PROJECT_CODE,
            "W30 Candidate Project",
            nvt_project_id=NVT_ID,
            status=project_status,
            start_date=date(2026, 1, 1),
            currency="KRW",
            project_request_code=(
                "VO00R260001" if project_origin == "APPROVED_APPLICATION" else None
            ),
            purpose_type=("D" if project_origin == "APPROVED_APPLICATION" else None),
            origin=project_origin,
            approval_evidence_ref=(
                "eos.project-approval:w30"
                if project_origin == "APPROVED_APPLICATION"
                else None
            ),
            approval_evidence_hash=(
                PROOF_HASH if project_origin == "APPROVED_APPLICATION" else None
            ),
        )
    )
    accounts = SqlAlchemyEosAccountRepository(sessions)
    accounts.create_account(
        AccountInput(
            TENANT,
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
            TENANT,
            CREDIT_ID,
            "CASH",
            "Cash",
            "ASSET",
            "GENERAL",
            date(2026, 1, 1),
        )
    )
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=DOCUMENT_OPERATION_ID,
                idempotency_key="w30-s3-01-approved-document",
                operation="APPROVE_BUSINESS_DOCUMENT",
                payload_hash=PAYLOAD_HASH,
                commit_state="COMMITTED",
                result_json={"envelope_id": ENVELOPE_ID},
                created_at=NOW - timedelta(hours=2),
                committed_at=NOW - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_APPROVAL_POLICY_TABLE.insert().values(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="mybee.w30.s3-01.document",
                version=1,
                name="W30 S3-01 document approval",
                approval_domain="BUSINESS_FORMAL",
                risk_level="MEDIUM",
                minimum_amount=None,
                maximum_amount=None,
                project_id=PROJECT_ID,
                account_id=None,
                transaction_type="DOCUMENT_SIGNOFF",
                status="ACTIVE",
                effective_from=NOW - timedelta(days=2),
                effective_until=None,
                policy_hash=POLICY_HASH,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW - timedelta(days=2),
            )
        )
        session.execute(
            EOS_SCOPED_APPROVAL_CASE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                idempotency_key="w30-s3-01-scoped-case",
                company_id=COMPANY_ID,
                purpose="DOCUMENT_SIGNOFF",
                scope_type="PROJECT",
                project_set_hash=PROOF_HASH,
                subject_ref="mybee.proposal:travel-proposal-2026-0001",
                subject_revision=1,
                subject_hash=DOCUMENT_HASH,
                requester_ref_type="oa.user",
                requester_id="employee-1001",
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=POLICY_HASH,
                oa_decision_ref="oa.authorization:w30-s3-01",
                authorization_revision_hash=PROOF_HASH,
                authorization_checked_at=NOW - timedelta(days=1),
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                target_role_ref="TEAM_LEAD",
                version=2,
                case_hash="sha256:" + "1" * 64,
                created_business_operation_id=DOCUMENT_OPERATION_ID,
                correlation_id="correlation-w30-s3-01",
                causation_id="causation-w30-s3-01",
                expires_at=NOW + timedelta(days=30),
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(hours=1),
                decided_at=NOW - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                evidence_id=EVIDENCE_ID,
                company_id=COMPANY_ID,
                envelope_id=ENVELOPE_ID,
                context_hash="sha256:" + "2" * 64,
                document_payload_hash=PAYLOAD_HASH,
                approver_subject_id="approver-2001",
                approval_policy_hash=POLICY_HASH,
                wc_work_item_id="32000000-0000-4000-8000-000000000014",
                wc_final_decision_id="32000000-0000-4000-8000-000000000015",
                oa_authorization_revision_hash=PROOF_HASH,
                decided_at=NOW - timedelta(hours=1),
                proof_hash=PROOF_HASH,
                created_at=NOW - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_APPROVED_DOCUMENT_TABLE.insert().values(
                tenant_id=TENANT,
                envelope_id=ENVELOPE_ID,
                company_id=COMPANY_ID,
                approved_document_id="travel-proposal-2026-0001",
                document_revision=1,
                document_type="BUSINESS_PROPOSAL",
                work_code="FL0004011",
                document_content_hash=DOCUMENT_HASH,
                attachment_manifest_hash=ATTACHMENT_HASH,
                business_approval_proof_id=None,
                scoped_document_evidence_id=EVIDENCE_ID,
                business_proof_hash=PROOF_HASH,
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=POLICY_HASH,
                scope_type="PROJECT",
                project_set_hash=PROOF_HASH,
                allowed_project_ids=[PROJECT_ID],
                allowed_project_codes=list(allowed_project_codes),
                approved_amount=Decimal("10000.0000"),
                approved_currency="KRW",
                tolerance_policy_hash=None,
                valid_from=NOW - timedelta(days=1),
                valid_until=NOW + timedelta(days=30),
                state=document_state,
                approved_at=NOW - timedelta(days=1),
                approved_by_ref_type="oa.user",
                approved_by_id="approver-2001",
                source_work_item_ref="wc.approval:w30-s3-01",
                payload_hash=PAYLOAD_HASH,
                created_business_operation_id=DOCUMENT_OPERATION_ID,
                created_at=NOW - timedelta(days=1),
            )
        )


def _runtime(**seed_options):
    engine = _engine()
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed(sessions, **seed_options)
    authorization = AuthorizationSource()
    ids = iter((CANDIDATE_ID, REVISION_ID))
    repository = SqlAlchemyEosVoucherCandidateRepository(
        sessions,
        clock=lambda: NOW,
    )
    service = EosCreateVoucherCandidateService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            id_factory=lambda: str(uuid.uuid4()),
            clock=lambda: NOW,
        ),
        candidates=repository,
        authorizer=EosVoucherAuthorizationClient(
            authorization,
            required_scope="finance:voucher-candidate:create",
            clock=lambda: NOW,
        ),
        id_factory=lambda: next(ids),
        clock=lambda: NOW,
    )
    return engine, sessions, repository, service, authorization


def _payload(**overrides):
    payload = {
        "schema_version": "eos_voucher_candidate_create.v2",
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "idempotency_key": "w30-s3-01-candidate",
        "payload_hash": "sha256:" + "0" * 64,
        "preparer_subject_id": "employee-1001",
        "project_ref": {
            "type": "eos.project",
            "id": PROJECT_ID,
            "code": PROJECT_CODE,
        },
        "business_approval": {
            "envelope_id": ENVELOPE_ID,
            "approved_document_id": "travel-proposal-2026-0001",
            "document_revision": 1,
            "approved_document_hash": DOCUMENT_HASH,
            "attachment_manifest_hash": ATTACHMENT_HASH,
        },
        "candidate": {
            "source_kind": "EXPENSE_CLAIM",
            "source_record_ref": "mybee.expense:travel-2026-0001",
            "business_work_code": "FL0004011",
            "transaction_currency": "KRW",
            "recognition_date": "2026-11-12",
            "lines": [
                {
                    "line_no": 1,
                    "account_ref": {"type": "eos.account", "id": DEBIT_ID},
                    "debit_original": "10000.0000",
                    "credit_original": "0.0000",
                    "source_record_line_ref": "expense-line-1",
                    "description": "Travel expense",
                    "evidence_hash": EVIDENCE_HASH,
                },
                {
                    "line_no": 2,
                    "account_ref": {"type": "eos.account", "id": CREDIT_ID},
                    "debit_original": "0.0000",
                    "credit_original": "10000.0000",
                    "source_record_line_ref": "expense-line-2",
                    "description": "Cash offset",
                    "evidence_hash": EVIDENCE_HASH,
                },
            ],
        },
        "trace": {
            "trace_id": "trace-w30-s3-01",
            "correlation_id": "correlation-w30-s3-01",
            "causation_id": "causation-w30-s3-01",
        },
    }
    payload.update(overrides)
    payload["payload_hash"] = voucher_candidate_payload_hash(payload)
    return payload


def _candidate_input() -> VoucherCandidateInput:
    command = parse_create_voucher_candidate_command(_payload())
    return VoucherCandidateInput(
        tenant_id=command.tenant_id,
        candidate_id=CANDIDATE_ID,
        revision_id=REVISION_ID,
        company_id=command.company_id,
        project_id=command.project_id,
        project_code=command.project_code,
        document_envelope_id=command.document_envelope_id,
        approved_document_id=command.approved_document_id,
        document_revision=command.document_revision,
        approved_document_hash=command.approved_document_hash,
        attachment_manifest_hash=command.attachment_manifest_hash,
        preparer_subject_id=command.preparer_subject_id,
        source_kind=command.source_kind,
        source_record_ref=command.source_record_ref,
        business_work_code=command.business_work_code,
        transaction_currency=command.transaction_currency,
        recognition_date=command.recognition_date,
        lines=command.lines,
        created_business_operation_id=command.business_operation_id,
    )


def _admit_service_token(monkeypatch) -> None:
    monkeypatch.setattr(
        finance_v2_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api",
            audience="nex-eos",
            scopes=("service:call",),
        ),
    )


CALLER = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def test_s3_01_migration_contract_and_openapi_are_additive() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2534_eos_voucher_candidate_v2"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_voucher_candidate" in compact
    assert "create table if not exists eos_voucher_candidate_revision" in compact
    assert "create table if not exists eos_voucher_candidate_line" in compact
    assert "trg_eos_candidate_revision_immutable" in compact
    assert "trg_eos_candidate_line_immutable" in compact
    assert "project_code ~ '^[a-z0-9]{4}[dmsoig][0-9]{6}$'" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_VOUCHER_CANDIDATE_TABLE,
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
            EOS_VOUCHER_CANDIDATE_LINE_TABLE,
        )
        for constraint in table.constraints
    )

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"]["/internal/v2/finance/voucher-candidates"]["post"]
    assert route["operationId"] == "FINANCE.VOUCHER_CANDIDATE.CREATE_V2"
    assert route["x-nex-business-scope"] == "finance:voucher-candidate:create"
    assert "/internal/v1/finance/voucher-drafts" in spec["paths"]


def test_candidate_create_replay_and_projection_are_immutable() -> None:
    _engine_value, sessions, repository, service, _authorization = _runtime()
    payload = _payload()

    created = service.execute(payload, caller=CALLER)
    replayed = service.execute(payload, caller=CALLER)
    loaded = repository.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)

    assert created["idempotency_disposition"] == "CREATED"
    assert replayed["idempotency_disposition"] == "REPLAYED"
    assert replayed["candidate_ref"] == created["candidate_ref"]
    assert created["project_ref"]["code"] == PROJECT_CODE
    assert loaded is not None
    assert loaded["state"] == "DRAFT"
    assert loaded["project_code"] == PROJECT_CODE
    assert loaded["revision"]["candidate_hash"].startswith("sha256:")
    assert loaded["revision"]["source_evidence_hash"] == PROOF_HASH
    assert [line["project_code"] for line in loaded["lines"]] == [
        PROJECT_CODE,
        PROJECT_CODE,
    ]
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_TABLE)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_REVISION_TABLE)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
            )
            == 2
        )


def test_finance_v2_api_create_replay_get_and_not_found(monkeypatch) -> None:
    _admit_service_token(monkeypatch)
    _engine_value, _sessions, repository, service, _authorization = _runtime()
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_voucher_candidate_command_service = service
    app.state.eos_voucher_candidates = repository

    with TestClient(app) as client:
        created = client.post(
            "/internal/v2/finance/voucher-candidates",
            json=_payload(),
            headers={"Authorization": "Bearer service-token"},
        )
        replayed = client.post(
            "/internal/v2/finance/voucher-candidates",
            json=_payload(),
            headers={"Authorization": "Bearer service-token"},
        )
        loaded = client.get(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}",
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": TENANT,
            },
        )
        missing = client.get(
            f"/internal/v2/finance/voucher-candidates/{uuid.uuid4()}",
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": TENANT,
            },
        )

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert loaded.status_code == 200
    assert loaded.json()["project_code"] == PROJECT_CODE
    assert missing.status_code == 404


def test_finance_v2_api_fail_closed_boundaries(monkeypatch) -> None:
    _admit_service_token(monkeypatch)
    app = FastAPI()
    register_finance_v2_routes(app)
    with TestClient(app) as client:
        unavailable_write = client.post(
            "/internal/v2/finance/voucher-candidates",
            json=_payload(),
            headers={"Authorization": "Bearer service-token"},
        )
        unavailable_read = client.get(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}",
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": TENANT,
            },
        )
    assert unavailable_write.status_code == 503
    assert unavailable_read.status_code == 503

    class DeniedService:
        def execute(self, _payload, *, caller):
            raise EosVoucherCandidateCommandError(
                "EOS_VOUCHER_CANDIDATE_DENIED",
                f"Denied for {caller.subject}.",
                status_code=403,
            )

    class BrokenRepository:
        def get(self, *, tenant_id, candidate_id):
            raise EosVoucherCandidateError(
                "EOS_VOUCHER_CANDIDATE_PERSISTENCE_FAILED",
                f"Unavailable for {tenant_id}:{candidate_id}.",
                status_code=503,
                retryable=True,
            )

    app.state.eos_voucher_candidate_command_service = DeniedService()
    app.state.eos_voucher_candidates = BrokenRepository()
    with TestClient(app) as client:
        denied = client.post(
            "/internal/v2/finance/voucher-candidates",
            json=_payload(),
            headers={"Authorization": "Bearer service-token"},
        )
        failed = client.get(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}",
            headers={
                "Authorization": "Bearer service-token",
                "X-NeX-Tenant-Id": TENANT,
            },
        )
    assert denied.status_code == 403
    assert failed.status_code == 503


def test_finance_v2_api_propagates_service_token_denial(monkeypatch) -> None:
    monkeypatch.setattr(
        finance_v2_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: JSONResponse(
            {"error_code": "SERVICE_TOKEN_DENIED"}, status_code=403
        ),
    )
    app = FastAPI()
    register_finance_v2_routes(app)
    with TestClient(app) as client:
        denied_write = client.post(
            "/internal/v2/finance/voucher-candidates",
            json=_payload(),
        )
        denied_read = client.get(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}",
            headers={"X-NeX-Tenant-Id": TENANT},
        )
    assert denied_write.status_code == 403
    assert denied_read.status_code == 403


@pytest.mark.parametrize(
    ("seed_options", "mutator", "expected"),
    (
        ({"project_origin": "LEGACY_DIRECT"}, None, "active approved application"),
        ({"project_status": "INACTIVE"}, None, "active approved application"),
        ({"document_state": "REVOKED"}, None, "not currently active"),
        ({"allowed_project_codes": ()}, None, "does not admit"),
        (
            {},
            lambda value: value["project_ref"].update(code="VO00D260099"),
            "does not admit",
        ),
        (
            {},
            lambda value: value["business_approval"].update(
                approved_document_hash="sha256:" + "9" * 64
            ),
            "does not match",
        ),
    ),
)
def test_unapproved_project_or_document_lineage_creates_zero_candidate(
    seed_options,
    mutator,
    expected,
) -> None:
    _engine_value, sessions, _repository, service, _authorization = _runtime(
        **seed_options
    )
    payload = _payload()
    if mutator is not None:
        mutator(payload)
        payload["payload_hash"] = voucher_candidate_payload_hash(payload)
    with pytest.raises(EosVoucherCandidateCommandError) as error:
        service.execute(payload, caller=CALLER)
    assert expected in error.value.detail
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_TABLE)
            )
            == 0
        )


def test_command_hash_authorization_and_line_shape_fail_closed() -> None:
    _engine_value, sessions, _repository, service, authorization = _runtime()
    payload = _payload()
    payload["payload_hash"] = "sha256:" + "9" * 64
    with pytest.raises(EosVoucherCandidateCommandError) as mismatch:
        service.execute(payload, caller=CALLER)
    assert mismatch.value.error_code == "EOS_VOUCHER_CANDIDATE_PAYLOAD_HASH_MISMATCH"

    authorization.scopes = []
    with pytest.raises(EosVoucherCandidateCommandError) as denied:
        service.execute(_payload(), caller=CALLER)
    assert denied.value.status_code == 403

    malformed = _payload()
    malformed["candidate"]["lines"][0]["credit_original"] = "1.0000"
    malformed["payload_hash"] = "sha256:" + "0" * 64
    with pytest.raises(EosVoucherCandidateCommandError) as invalid:
        parse_create_voucher_candidate_command(malformed)
    assert invalid.value.error_code == "EOS_VOUCHER_CANDIDATE_COMMAND_INVALID"
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_TABLE)
            )
            == 0
        )


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.update(schema_version="unsupported"),
        lambda value: value["project_ref"].update(type="wrong.project"),
        lambda value: value["project_ref"].update(id="not-a-uuid"),
        lambda value: value["project_ref"].update(code="INVALID"),
        lambda value: value["business_approval"].update(document_revision=0),
        lambda value: value["business_approval"].update(
            approved_document_hash="not-a-hash"
        ),
        lambda value: value["candidate"].update(recognition_date="not-a-date"),
        lambda value: value["candidate"].update(lines="not-an-array"),
        lambda value: value["candidate"].update(lines=value["candidate"]["lines"][:1]),
        lambda value: value["candidate"]["lines"][1].update(line_no=3),
        lambda value: value["candidate"]["lines"][0]["account_ref"].update(
            type="wrong.account"
        ),
        lambda value: value["candidate"]["lines"][0].update(debit_original="10"),
        lambda value: value["candidate"]["lines"][0].update(description=""),
        lambda value: value["trace"].update(trace_id="bad space"),
        lambda value: value.pop("trace"),
    ),
)
def test_command_parser_rejects_malformed_contract(mutator) -> None:
    payload = _payload()
    mutator(payload)
    with pytest.raises(EosVoucherCandidateCommandError) as error:
        parse_create_voucher_candidate_command(payload)
    assert error.value.error_code == "EOS_VOUCHER_CANDIDATE_COMMAND_INVALID"


@pytest.mark.parametrize(
    "operation",
    (
        lambda value: voucher_candidates._candidate_semantics(object()),
        lambda value: voucher_candidates._candidate_semantics(
            replace(value, project_code="INVALID")
        ),
        lambda value: voucher_candidates._lines("not-lines"),
        lambda value: voucher_candidates._lines(value.lines[:1]),
        lambda value: voucher_candidates._lines((object(), object())),
        lambda value: voucher_candidates._lines(
            (
                replace(
                    value.lines[0],
                    debit_original=Decimal("0.0000"),
                    credit_original=Decimal("0.0000"),
                ),
                value.lines[1],
            )
        ),
        lambda value: voucher_candidates._uuid("candidate_id", "bad"),
        lambda value: voucher_candidates._scoped_id("tenant_id", "bad space", 128),
        lambda value: voucher_candidates._code("source_kind", "1bad"),
        lambda value: voucher_candidates._work_code("bad"),
        lambda value: voucher_candidates._currency("KR"),
        lambda value: voucher_candidates._hash_ref("hash", "bad"),
        lambda value: voucher_candidates._text("description", "", 10),
        lambda value: voucher_candidates._date("date", NOW),
        lambda value: voucher_candidates._aware_datetime(
            "clock", NOW.replace(tzinfo=None)
        ),
        lambda value: voucher_candidates._stored_time("bad"),
        lambda value: voucher_candidates._positive_int("revision", True),
        lambda value: voucher_candidates._nonnegative_money(
            "amount", Decimal("1.00001")
        ),
    ),
)
def test_candidate_persistence_contract_rejects_malformed_values(operation) -> None:
    with pytest.raises(EosVoucherCandidateError) as error:
        operation(_candidate_input())
    assert error.value.error_code == "EOS_VOUCHER_CANDIDATE_INVALID"


def test_repository_conflict_and_database_unavailability_are_typed() -> None:
    engine, _sessions, repository, service, _authorization = _runtime()
    service.execute(_payload(), caller=CALLER)
    with pytest.raises(EosVoucherCandidateError) as conflict:
        repository.create(_candidate_input())
    assert conflict.value.status_code == 409

    engine.dispose()
    with pytest.raises(EosVoucherCandidateError) as unavailable:
        repository.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_command_requires_transaction_and_timezone_aware_clock() -> None:
    _engine_value, sessions, repository, _service, authorization = _runtime()
    authorizer = EosVoucherAuthorizationClient(
        authorization,
        required_scope="finance:voucher-candidate:create",
        clock=lambda: NOW,
    )

    class NullSessionCoordinator:
        def execute(self, _request, mutation):
            return mutation(None)

    transaction_required = EosCreateVoucherCandidateService(
        coordinator=NullSessionCoordinator(),
        candidates=repository,
        authorizer=authorizer,
        id_factory=lambda: str(uuid.uuid4()),
        clock=lambda: NOW,
    )
    with pytest.raises(EosVoucherCandidateCommandError) as missing_transaction:
        transaction_required.execute(_payload(), caller=CALLER)
    assert (
        missing_transaction.value.error_code
        == "EOS_VOUCHER_CANDIDATE_TRANSACTION_REQUIRED"
    )

    ids = iter((CANDIDATE_ID, REVISION_ID))
    invalid_clock = EosCreateVoucherCandidateService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            clock=lambda: NOW,
        ),
        candidates=repository,
        authorizer=authorizer,
        id_factory=lambda: next(ids),
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(EosVoucherCandidateCommandError) as clock_error:
        invalid_clock.execute(_payload(), caller=CALLER)
    assert clock_error.value.error_code == "EOS_VOUCHER_CANDIDATE_CLOCK_INVALID"


def test_missing_account_cross_tenant_query_and_persistence_failure(
    monkeypatch,
) -> None:
    _engine_value, _sessions, repository, service, _authorization = _runtime()
    payload = _payload()
    payload["candidate"]["lines"][0]["account_ref"]["id"] = str(uuid.uuid4())
    payload["payload_hash"] = voucher_candidate_payload_hash(payload)
    with pytest.raises(EosVoucherCandidateCommandError) as missing:
        service.execute(payload, caller=CALLER)
    assert "account identities do not exist" in missing.value.detail
    assert repository.get(tenant_id="OTHER", candidate_id=CANDIDATE_ID) is None

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("broken")

    broken = SqlAlchemyEosVoucherCandidateRepository(BrokenFactory())
    with pytest.raises(RuntimeError):
        broken.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W30-S3-01 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_migration_immutability_and_zero_residue() -> None:
    schema_name = f"mybee_w30s301_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2534_eos_voucher_candidate_v2" in result.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed(sessions)
        authorization = AuthorizationSource()
        ids = iter((CANDIDATE_ID, REVISION_ID))
        repository = SqlAlchemyEosVoucherCandidateRepository(
            sessions, clock=lambda: NOW
        )
        service = EosCreateVoucherCandidateService(
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                sessions, clock=lambda: NOW
            ),
            candidates=repository,
            authorizer=EosVoucherAuthorizationClient(
                authorization,
                required_scope="finance:voucher-candidate:create",
                clock=lambda: NOW,
            ),
            id_factory=lambda: next(ids),
            clock=lambda: NOW,
        )
        created = service.execute(_payload(), caller=CALLER)
        replayed = service.execute(_payload(), caller=CALLER)
        assert created["candidate_ref"] == replayed["candidate_ref"]
        session = sessions()
        try:
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_VOUCHER_CANDIDATE_REVISION_TABLE)
                    .where(EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == TENANT)
                    .values(created_by="tampered")
                )
            session.rollback()
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
                    .where(EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.tenant_id == TENANT)
                    .values(description="tampered")
                )
            session.rollback()
        finally:
            session.close()
        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
            assert cursor.fetchone() == (None,)
