from __future__ import annotations

import copy
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
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
    EOS_CANDIDATE_REVIEW_EVENT_TABLE,
    EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    EOS_VOUCHER_CANDIDATE_LINE_TABLE,
    EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
    EOS_VOUCHER_CANDIDATE_TABLE,
    AccountInput,
    EosCandidateReviewError,
    EosCreateVoucherCandidateService,
    EosReviseVoucherCandidateService,
    EosServiceCaller,
    EosVoucherAuthorizationClient,
    EosVoucherCandidateCommandError,
    EosVoucherCandidateError,
    LegalEntityInput,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosCandidateReviewRepository,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherCandidateRepository,
    VoucherCandidateInput,
    finance_v2_api,
    parse_create_voucher_candidate_command,
    parse_revise_voucher_candidate_command,
    voucher_candidate_payload_hash,
    voucher_candidate_revision_payload_hash,
    voucher_candidates,
)
from nex_eos import candidate_review as candidate_review_module
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_runtime import psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, func, make_url, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
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
REVIEW_CASE_ID = "32000000-0000-4000-8000-000000000020"
EVIDENCE_ID = "32000000-0000-4000-8000-000000000013"
DOCUMENT_HASH = "sha256:" + "a" * 64
ATTACHMENT_HASH = "sha256:" + "b" * 64
PROOF_HASH = "sha256:" + "c" * 64
POLICY_HASH = "sha256:" + "d" * 64
PAYLOAD_HASH = "sha256:" + "e" * 64
EVIDENCE_HASH = "sha256:" + "f" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S3_01_POSTGRES_SMOKE") == "1"
REVIEW_POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S3_03_POSTGRES_SMOKE") == "1"
REVISION_POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_W40_S4_00A_POSTGRES_SMOKE") == "1"
VALIDATION_HASH = "sha256:" + "9" * 64


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
            project_owner_subject_id=(
                "employee-owner" if project_origin == "APPROVED_APPLICATION" else None
            ),
            project_manager_subject_id=(
                "employee-manager" if project_origin == "APPROVED_APPLICATION" else None
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


def _runtime(*, engine=None, **seed_options):
    engine = engine or _engine()
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


def _candidate_review_fixture(sessions, repository):
    candidate = repository.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert candidate is not None
    with sessions.begin() as session:
        session.execute(
            EOS_SCOPED_APPROVAL_CASE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=REVIEW_CASE_ID,
                idempotency_key="w30-s3-03-candidate-review",
                company_id=COMPANY_ID,
                purpose="ACCOUNTING_POSTING",
                scope_type="PROJECT",
                project_set_hash=PROOF_HASH,
                subject_ref=f"eos.voucher-candidate:{CANDIDATE_ID}",
                subject_revision=1,
                subject_hash=candidate["revision"]["candidate_hash"],
                requester_ref_type="oa.user",
                requester_id="employee-1001",
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=POLICY_HASH,
                oa_decision_ref="oa.authorization:w30-s3-03",
                authorization_revision_hash=PROOF_HASH,
                authorization_checked_at=NOW,
                state="PENDING",
                active_stage_order=1,
                stage_count=1,
                target_role_ref="TEAM_LEAD",
                version=1,
                case_hash="sha256:" + "8" * 64,
                created_business_operation_id=BUSINESS_OPERATION_ID,
                correlation_id="correlation-w30-s3-03",
                causation_id="causation-w30-s3-03",
                expires_at=NOW + timedelta(days=7),
                created_at=NOW,
                updated_at=NOW,
                decided_at=None,
            )
        )
    case = {
        "tenant_id": TENANT,
        "case_id": REVIEW_CASE_ID,
        "company_id": COMPANY_ID,
        "purpose": "ACCOUNTING_POSTING",
        "subject_ref": f"eos.voucher-candidate:{CANDIDATE_ID}",
        "subject_revision": 1,
        "subject_hash": candidate["revision"]["candidate_hash"],
        "project_ids": [PROJECT_ID],
        "requester_ref": {"type": "oa.user", "id": "employee-1001"},
    }
    review = {
        "schema_version": "eos_accounting_review_context.v3",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_hash": candidate["revision"]["candidate_hash"],
        "candidate_version": 1,
        "validation_hash": VALIDATION_HASH,
        "validation_observed_at": NOW,
        "document_envelope_hash": DOCUMENT_HASH,
        "fx_rate_set_hash": PROOF_HASH,
        "rule_release_hash": POLICY_HASH,
        "accounting_period_id": "32000000-0000-4000-8000-000000000021",
        "candidate_preparer_subject_id": "employee-1001",
        "business_approver_subject_ids": ["business-approver"],
        "original_currency": "KRW",
        "original_amount": "10000",
        "market_base_rate": "1",
        "rate_reference_date": "2026-11-12",
        "rate_publication": "SAME_CURRENCY",
        "functional_currency": "KRW",
        "functional_amount": "10000",
        "fx_exception": None,
    }
    validation = {
        "schema_version": "eos_voucher_candidate_validation.v1",
        "status": "PASS",
        "tenant_id": TENANT,
        "candidate_ref": {"id": CANDIDATE_ID},
        "candidate_version": 1,
        "revision_ref": {
            "revision_no": 1,
            "hash": candidate["revision"]["candidate_hash"],
        },
        "company_id": COMPANY_ID,
        "project_ref": {"id": PROJECT_ID},
        "document_ref": {"id": ENVELOPE_ID, "hash": DOCUMENT_HASH},
        "accounting_period_id": review["accounting_period_id"],
        "posting_rule_release_hash": POLICY_HASH,
        "fx_rate_set_hash": PROOF_HASH,
        "preparer_subject_id": "employee-1001",
        "transaction_currency": "KRW",
        "functional_currency": "KRW",
        "validation_hash": VALIDATION_HASH,
        "observed_at": NOW.isoformat(),
        "fx_evidence": {"normalized_rate": "1"},
        "totals": {
            "debit_original": "10000",
            "debit_functional": "10000",
        },
    }
    return case, review, validation


def _review_invalidation_payload(review, **overrides):
    payload = {
        "schema_version": "eos_candidate_review_invalidate.v1",
        "tenant_id": TENANT,
        "event_id": str(uuid.uuid4()),
        "candidate_id": CANDIDATE_ID,
        "approval_case_id": REVIEW_CASE_ID,
        "expected_candidate_version": 2,
        "expected_revision_no": 1,
        "expected_candidate_hash": review["candidate_hash"],
        "actor_subject_id": "accounting-controller",
        "reason": "Candidate accounting inputs changed after review submission.",
        "invalidated_at": (NOW + timedelta(minutes=2)).isoformat(),
    }
    payload.update(overrides)
    return payload


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


def _revision_payload(
    *,
    candidate_hash: str,
    return_event_id: str,
    amount: str = "12000.0000",
    operation_id: str = "32000000-0000-4000-8000-000000000030",
    idempotency_key: str = "w40-s4-00a-candidate-revision-2",
):
    payload = {
        "schema_version": "eos_voucher_candidate_revise.v1",
        "tenant_id": TENANT,
        "business_operation_id": operation_id,
        "idempotency_key": idempotency_key,
        "payload_hash": "sha256:" + "0" * 64,
        "actor_subject_id": "employee-1001",
        "candidate_ref": {
            "type": "eos.voucher_candidate",
            "id": CANDIDATE_ID,
            "expected_version": 3,
            "expected_revision_no": 1,
            "expected_hash": candidate_hash,
        },
        "return_event_ref": {
            "type": "eos.candidate_review_event",
            "id": return_event_id,
        },
        "replacement": {
            "lines": [
                {
                    "line_no": 1,
                    "account_ref": {"type": "eos.account", "id": DEBIT_ID},
                    "debit_original": amount,
                    "credit_original": "0.0000",
                    "source_record_line_ref": "expense-line-1-corrected",
                    "description": "Corrected travel expense",
                    "evidence_hash": EVIDENCE_HASH,
                },
                {
                    "line_no": 2,
                    "account_ref": {"type": "eos.account", "id": CREDIT_ID},
                    "debit_original": "0.0000",
                    "credit_original": amount,
                    "source_record_line_ref": "expense-line-2-corrected",
                    "description": "Corrected cash offset",
                    "evidence_hash": EVIDENCE_HASH,
                },
            ]
        },
        "trace": {
            "trace_id": "trace-w40-s4-00a",
            "correlation_id": "correlation-w40-s4-00a",
            "causation_id": "causation-w40-s4-00a",
        },
    }
    payload["payload_hash"] = voucher_candidate_revision_payload_hash(payload)
    return payload


def _returned_candidate_runtime():
    engine, sessions, candidates, command, authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
    with sessions.begin() as session:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    with sessions.begin() as session:
        returned = reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason="Correct the expense amount and evidence.",
            decided_at=NOW + timedelta(minutes=1),
        )
    assert returned is not None
    service = EosReviseVoucherCandidateService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions,
            id_factory=lambda: str(uuid.uuid4()),
            clock=lambda: NOW + timedelta(minutes=2),
        ),
        candidates=candidates,
        reviews=reviews,
        authorizer=EosVoucherAuthorizationClient(
            authorization,
            required_scope="finance:voucher-candidate:create",
            clock=lambda: NOW + timedelta(minutes=2),
        ),
        id_factory=lambda: "32000000-0000-4000-8000-000000000031",
        clock=lambda: NOW + timedelta(minutes=2),
    )
    return engine, sessions, candidates, reviews, service, review, returned


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


def test_candidate_review_submit_replay_invalidate_and_stale_decision_guard() -> None:
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)

    with sessions.begin() as session:
        submitted = reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    with sessions.begin() as session:
        replay = reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )

    assert submitted == replay
    assert submitted["transition_kind"] == "SUBMIT"
    projection = reviews.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert projection is not None
    assert projection["state"] == "READY_FOR_REVIEW"
    assert projection["candidate_version"] == 2
    assert len(projection["events"]) == 1

    invalidation = {
        "schema_version": "eos_candidate_review_invalidate.v1",
        "tenant_id": TENANT,
        "event_id": str(uuid.uuid4()),
        "candidate_id": CANDIDATE_ID,
        "approval_case_id": REVIEW_CASE_ID,
        "expected_candidate_version": 2,
        "expected_revision_no": 1,
        "expected_candidate_hash": review["candidate_hash"],
        "actor_subject_id": "accounting-controller",
        "reason": "Candidate accounting inputs changed after review submission.",
        "invalidated_at": (NOW + timedelta(minutes=2)).isoformat(),
    }
    invalidated = reviews.invalidate(invalidation)
    assert reviews.invalidate(invalidation) == invalidated
    assert invalidated["transition_kind"] == "INVALIDATE"
    assert invalidated["to_state"] == "RETURNED_FOR_CORRECTION"
    with (
        sessions.begin() as session,
        pytest.raises(EosCandidateReviewError) as stale,
    ):
        reviews.require_current_review_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
        )
    assert stale.value.status_code == 409
    projection = reviews.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert projection is not None
    assert projection["candidate_version"] == 3
    assert [event["transition_kind"] for event in projection["events"]] == [
        "SUBMIT",
        "INVALIDATE",
    ]


def test_s3_03_migration_and_openapi_contract_are_additive() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2535_eos_candidate_review_state"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_candidate_review_event" in compact
    assert "trg_eos_candidate_review_immutable" in compact
    assert "returned_for_correction" in compact
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for constraint in EOS_CANDIDATE_REVIEW_EVENT_TABLE.constraints
    )
    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    review_path = spec["paths"][
        "/internal/v2/finance/voucher-candidates/{candidate_id}/review"
    ]["get"]
    invalidate_path = spec["paths"][
        "/internal/v2/finance/voucher-candidates/{candidate_id}/review-invalidation"
    ]["post"]
    assert review_path["operationId"] == "FINANCE.VOUCHER_CANDIDATE.REVIEW_GET"
    assert review_path["x-nex-side-effect-free"] is True
    assert (
        invalidate_path["operationId"] == "FINANCE.VOUCHER_CANDIDATE.INVALIDATE_REVIEW"
    )


def test_candidate_review_query_and_invalidation_api(monkeypatch) -> None:
    _admit_service_token(monkeypatch)
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
    with sessions.begin() as session:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_candidate_review_repository = reviews
    client = TestClient(app)

    loaded = client.get(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/review",
        headers={
            "Authorization": "Bearer service-token",
            "X-NeX-Tenant-Id": TENANT,
        },
    )
    assert loaded.status_code == 200
    assert loaded.json()["state"] == "READY_FOR_REVIEW"

    payload = {
        "schema_version": "eos_candidate_review_invalidate.v1",
        "tenant_id": TENANT,
        "event_id": str(uuid.uuid4()),
        "candidate_id": CANDIDATE_ID,
        "approval_case_id": REVIEW_CASE_ID,
        "expected_candidate_version": 2,
        "expected_revision_no": 1,
        "expected_candidate_hash": review["candidate_hash"],
        "actor_subject_id": "accounting-controller",
        "reason": "Invalidate stale review.",
        "invalidated_at": (NOW + timedelta(minutes=2)).isoformat(),
    }
    mismatch = client.post(
        f"/internal/v2/finance/voucher-candidates/{uuid.uuid4()}/review-invalidation",
        json=payload,
        headers={"Authorization": "Bearer service-token"},
    )
    assert mismatch.status_code == 422
    invalidated = client.post(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/review-invalidation",
        json=payload,
        headers={"Authorization": "Bearer service-token"},
    )
    assert invalidated.status_code == 200
    assert invalidated.json()["transition_kind"] == "INVALIDATE"

    del app.state.eos_candidate_review_repository
    unavailable = client.get(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/review",
        headers={
            "Authorization": "Bearer service-token",
            "X-NeX-Tenant-Id": TENANT,
        },
    )
    assert unavailable.status_code == 503


def test_candidate_review_rejection_requires_reason_and_is_exactly_once() -> None:
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
    with sessions.begin() as session:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )

    with (
        pytest.raises(EosCandidateReviewError) as missing_reason,
        sessions.begin() as session,
    ):
        reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason=None,
            decided_at=NOW + timedelta(minutes=1),
        )
    assert missing_reason.value.status_code == 422

    with sessions.begin() as session:
        returned = reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason="Correct the expense evidence.",
            decided_at=NOW + timedelta(minutes=1),
        )
    with sessions.begin() as session:
        replay = reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason="Correct the expense evidence.",
            decided_at=NOW + timedelta(minutes=1),
        )
    assert returned == replay
    assert returned is not None
    assert returned["transition_kind"] == "RETURN"
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_CANDIDATE_REVIEW_EVENT_TABLE)
            )
            == 2
        )


def test_candidate_revision_appends_immutable_revision_and_replays_exactly_once() -> (
    None
):
    (
        _engine_value,
        sessions,
        candidates,
        _reviews,
        service,
        review,
        returned,
    ) = _returned_candidate_runtime()
    payload = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=returned["event_id"],
    )

    parsed = parse_revise_voucher_candidate_command(payload)
    assert parsed.expected_candidate_version == 3
    assert parsed.expected_revision_no == 1
    created = service.execute(CANDIDATE_ID, payload, caller=CALLER)
    replayed = service.execute(CANDIDATE_ID, payload, caller=CALLER)

    assert created["idempotency_disposition"] == "CREATED"
    assert replayed["idempotency_disposition"] == "REPLAYED"
    assert created["revision_ref"] == replayed["revision_ref"]
    assert created["revision_ref"]["revision_no"] == 2
    assert created["candidate_ref"] == {
        "type": "eos.voucher_candidate",
        "id": CANDIDATE_ID,
        "state": "DRAFT",
        "version": 4,
    }
    projected = candidates.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert projected is not None
    assert projected["current_revision_no"] == 2
    assert projected["revision"]["candidate_hash"] != review["candidate_hash"]
    assert projected["lines"][0]["debit_original"] == Decimal("12000.0000")
    with sessions() as session:
        revisions = (
            session.execute(
                select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE)
                .where(
                    EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == TENANT,
                    EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id == CANDIDATE_ID,
                )
                .order_by(EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no)
            )
            .mappings()
            .all()
        )
        assert [row["revision_no"] for row in revisions] == [1, 2]
        assert revisions[0]["candidate_hash"] == review["candidate_hash"]
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
            )
            == 4
        )
        event = (
            session.execute(
                select(EOS_OUTBOX_TABLE).where(
                    EOS_OUTBOX_TABLE.c.event_type == "VOUCHER_CANDIDATE_REVISED"
                )
            )
            .mappings()
            .one()
        )
        assert event["business_operation_id"] == payload["business_operation_id"]


def test_candidate_revision_rejects_noop_stale_return_and_changed_replay() -> None:
    (
        _engine_value,
        _sessions,
        _candidates,
        _reviews,
        service,
        review,
        returned,
    ) = _returned_candidate_runtime()
    no_change = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=returned["event_id"],
    )
    for index, line in enumerate(no_change["replacement"]["lines"], start=1):
        line["source_record_line_ref"] = f"expense-line-{index}"
        line["description"] = "Travel expense" if index == 1 else "Cash offset"
        line["debit_original"] = "10000.0000" if index == 1 else "0.0000"
        line["credit_original"] = "0.0000" if index == 1 else "10000.0000"
    no_change["payload_hash"] = voucher_candidate_revision_payload_hash(no_change)
    with pytest.raises(EosVoucherCandidateCommandError) as noop:
        service.execute(CANDIDATE_ID, no_change, caller=CALLER)
    assert noop.value.error_code == "EOS_VOUCHER_CANDIDATE_REVISION_NO_CHANGE"

    stale_event = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=str(uuid.uuid4()),
        operation_id="32000000-0000-4000-8000-000000000032",
        idempotency_key="w40-s4-00a-stale-return",
    )
    with pytest.raises(EosVoucherCandidateCommandError) as stale:
        service.execute(CANDIDATE_ID, stale_event, caller=CALLER)
    assert stale.value.status_code == 409

    payload = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=returned["event_id"],
        operation_id="32000000-0000-4000-8000-000000000033",
        idempotency_key="w40-s4-00a-changed-replay",
    )
    service.execute(CANDIDATE_ID, payload, caller=CALLER)
    changed = copy.deepcopy(payload)
    changed["replacement"]["lines"][0]["description"] = "Changed replay"
    changed["payload_hash"] = voucher_candidate_revision_payload_hash(changed)
    with pytest.raises(EosVoucherCandidateCommandError) as conflict:
        service.execute(CANDIDATE_ID, changed, caller=CALLER)
    assert conflict.value.status_code == 409


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.update(schema_version="unsupported"),
        lambda value: value["candidate_ref"].update(type="eos.voucher_draft"),
        lambda value: value["return_event_ref"].update(type="eos.review"),
        lambda value: value["replacement"].update(lines="not-an-array"),
        lambda value: value["replacement"].update(lines=[]),
        lambda value: value["replacement"]["lines"][0].update(line_no=2),
        lambda value: value["replacement"]["lines"][0]["account_ref"].update(
            type="eos.project"
        ),
        lambda value: value["replacement"]["lines"][0].update(credit_original="1.0000"),
        lambda value: value["candidate_ref"].update(id="not-a-uuid"),
        lambda value: value.update(tenant_id="bad tenant"),
        lambda value: value.update(idempotency_key=""),
        lambda value: value.update(payload_hash="not-a-hash"),
        lambda value: value["candidate_ref"].update(expected_version=True),
        lambda value: value["replacement"]["lines"][0].update(debit_original="12000"),
        lambda value: value.pop("return_event_ref"),
    ),
)
def test_candidate_revision_parser_rejects_malformed_commands(mutator) -> None:
    payload = _revision_payload(
        candidate_hash="sha256:" + "a" * 64,
        return_event_id="32000000-0000-4000-8000-000000000051",
    )
    mutator(payload)
    with pytest.raises(EosVoucherCandidateCommandError) as invalid:
        parse_revise_voucher_candidate_command(payload)
    assert invalid.value.status_code == 422


def test_candidate_revision_service_rejects_hash_authorization_and_missing_tx() -> None:
    (
        _engine_value,
        _sessions,
        _candidates,
        _reviews,
        service,
        review,
        returned,
    ) = _returned_candidate_runtime()
    payload = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=returned["event_id"],
    )
    changed_hash = copy.deepcopy(payload)
    changed_hash["payload_hash"] = "sha256:" + "f" * 64
    with pytest.raises(EosVoucherCandidateCommandError) as mismatch:
        service.execute(CANDIDATE_ID, changed_hash, caller=CALLER)
    assert mismatch.value.error_code == "EOS_VOUCHER_CANDIDATE_PAYLOAD_HASH_MISMATCH"

    source = service._authorizer._source
    source.active = False
    with pytest.raises(EosVoucherCandidateCommandError) as denied:
        service.execute(CANDIDATE_ID, payload, caller=CALLER)
    assert denied.value.status_code == 403
    source.active = True

    class MissingTransactionCoordinator:
        @staticmethod
        def execute(_request, mutation):
            mutation(None)

    service._coordinator = MissingTransactionCoordinator()
    with pytest.raises(EosVoucherCandidateCommandError) as transaction:
        service.execute(CANDIDATE_ID, payload, caller=CALLER)
    assert transaction.value.error_code == "EOS_VOUCHER_CANDIDATE_TRANSACTION_REQUIRED"


def test_candidate_revision_api_and_openapi_contract(monkeypatch) -> None:
    _admit_service_token(monkeypatch)
    (
        _engine_value,
        _sessions,
        _candidates,
        _reviews,
        service,
        review,
        returned,
    ) = _returned_candidate_runtime()
    payload = _revision_payload(
        candidate_hash=review["candidate_hash"],
        return_event_id=returned["event_id"],
    )
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_voucher_candidate_revision_service = service
    client = TestClient(app)

    mismatch = client.post(
        f"/internal/v2/finance/voucher-candidates/{uuid.uuid4()}/revisions",
        json=payload,
        headers={"Authorization": "Bearer service-token"},
    )
    assert mismatch.status_code == 422
    response = client.post(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/revisions",
        json=payload,
        headers={"Authorization": "Bearer service-token"},
    )
    assert response.status_code == 201
    del app.state.eos_voucher_candidate_revision_service
    unavailable = client.post(
        f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/revisions",
        json=payload,
        headers={"Authorization": "Bearer service-token"},
    )
    assert unavailable.status_code == 503

    spec = yaml.safe_load(
        Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    route = spec["paths"][
        "/internal/v2/finance/voucher-candidates/{candidate_id}/revisions"
    ]["post"]
    assert route["operationId"] == "FINANCE.VOUCHER_CANDIDATE.REVISE"
    assert route["x-nex-business-scope"] == "finance:voucher-candidate:create"


@pytest.mark.skipif(
    not DATABASE_URL or not REVISION_POSTGRES_SMOKE,
    reason="Protected W40-S4-00A EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_candidate_revision_race_immutability_and_zero_residue() -> (
    None
):
    schema_name = f"mybee_w40s400a_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2534_eos_voucher_candidate_v2" in migration.applied
        assert "2535_eos_candidate_review_state" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        (
            _engine_value,
            sessions,
            candidates,
            command,
            authorization,
        ) = _runtime(engine=engine)
        command.execute(_payload(), caller=CALLER)
        case, review, validation = _candidate_review_fixture(sessions, candidates)
        reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
        with sessions.begin() as session:
            reviews.submit_in_session(
                session,
                scoped_case=case,
                review=review,
                validation=validation,
            )
        with sessions.begin() as session:
            returned = reviews.return_from_rejection_in_session(
                session,
                tenant_id=TENANT,
                approval_case_id=REVIEW_CASE_ID,
                review=review,
                actor_subject_id="accountant-lead",
                reason="Correct the accounting proposal.",
                decided_at=NOW + timedelta(minutes=1),
            )
        assert returned is not None

        def revision_service(revision_id: str):
            return EosReviseVoucherCandidateService(
                coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                    sessions,
                    id_factory=lambda: str(uuid.uuid4()),
                    clock=lambda: NOW + timedelta(minutes=2),
                ),
                candidates=candidates,
                reviews=reviews,
                authorizer=EosVoucherAuthorizationClient(
                    authorization,
                    required_scope="finance:voucher-candidate:create",
                    clock=lambda: NOW + timedelta(minutes=2),
                ),
                id_factory=lambda: revision_id,
                clock=lambda: NOW + timedelta(minutes=2),
            )

        attempts = (
            (
                revision_service("32000000-0000-4000-8000-000000000041"),
                _revision_payload(
                    candidate_hash=review["candidate_hash"],
                    return_event_id=returned["event_id"],
                    amount="12000.0000",
                    operation_id="32000000-0000-4000-8000-000000000042",
                    idempotency_key="w40-s4-00a-race-a",
                ),
            ),
            (
                revision_service("32000000-0000-4000-8000-000000000043"),
                _revision_payload(
                    candidate_hash=review["candidate_hash"],
                    return_event_id=returned["event_id"],
                    amount="13000.0000",
                    operation_id="32000000-0000-4000-8000-000000000044",
                    idempotency_key="w40-s4-00a-race-b",
                ),
            ),
        )

        def execute_attempt(item):
            service, payload = item
            try:
                return "CREATED", service.execute(CANDIDATE_ID, payload, caller=CALLER)
            except EosVoucherCandidateCommandError as exc:
                return "CONFLICT", exc.error_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(execute_attempt, attempts))
        assert sorted(outcome[0] for outcome in outcomes) == ["CONFLICT", "CREATED"]
        assert (
            next(outcome[1] for outcome in outcomes if outcome[0] == "CONFLICT")
            == "EOS_VOUCHER_CANDIDATE_REVISION_STALE"
        )
        winner_index = next(
            index for index, outcome in enumerate(outcomes) if outcome[0] == "CREATED"
        )
        winner_service, winner_payload = attempts[winner_index]
        replay = winner_service.execute(CANDIDATE_ID, winner_payload, caller=CALLER)
        assert replay["idempotency_disposition"] == "REPLAYED"

        with sessions() as session:
            revisions = (
                session.execute(
                    select(EOS_VOUCHER_CANDIDATE_REVISION_TABLE)
                    .where(
                        EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == TENANT,
                        EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.candidate_id
                        == CANDIDATE_ID,
                    )
                    .order_by(EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.revision_no)
                )
                .mappings()
                .all()
            )
            assert [item["revision_no"] for item in revisions] == [1, 2]
            assert revisions[0]["candidate_hash"] == review["candidate_hash"]
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EOS_OUTBOX_TABLE)
                    .where(EOS_OUTBOX_TABLE.c.event_type == "VOUCHER_CANDIDATE_REVISED")
                )
                == 1
            )
            assert session.execute(
                text(
                    "SELECT to_regclass('eos_journal_header'), "
                    "to_regclass('eos_journal_line')"
                )
            ).one() == (None, None)
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_VOUCHER_CANDIDATE_REVISION_TABLE)
                    .where(EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == TENANT)
                    .values(created_by="tampered")
                )
                session.commit()
            session.rollback()
            with pytest.raises(DBAPIError):
                session.execute(
                    delete(EOS_VOUCHER_CANDIDATE_REVISION_TABLE).where(
                        EOS_VOUCHER_CANDIDATE_REVISION_TABLE.c.tenant_id == TENANT
                    )
                )
                session.commit()
            session.rollback()
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_VOUCHER_CANDIDATE_LINE_TABLE)
                    .where(EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.tenant_id == TENANT)
                    .values(description="tampered")
                )
                session.commit()
            session.rollback()
            with pytest.raises(DBAPIError):
                session.execute(
                    delete(EOS_VOUCHER_CANDIDATE_LINE_TABLE).where(
                        EOS_VOUCHER_CANDIDATE_LINE_TABLE.c.tenant_id == TENANT
                    )
                )
                session.commit()
            session.rollback()

        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)


@pytest.mark.parametrize(
    ("mutator", "expected_detail"),
    (
        (
            lambda case, review, validation: review.update(
                schema_version="eos_accounting_review_context.v2"
            ),
            "requires review v3",
        ),
        (
            lambda case, review, validation: case.update(purpose="EXPENSE_REVIEW"),
            "case does not match",
        ),
        (
            lambda case, review, validation: review.update(candidate_version=2),
            "version or revision changed",
        ),
        (
            lambda case, review, validation: validation.pop("fx_evidence"),
            "evidence is incomplete",
        ),
        (
            lambda case, review, validation: validation.update(status="FAIL"),
            "differs from review context",
        ),
        (
            lambda case, review, validation: validation["totals"].update(
                debit_original="not-a-decimal"
            ),
            "amount evidence is malformed",
        ),
        (
            lambda case, review, validation: validation["totals"].update(
                debit_original="9999"
            ),
            "amounts differ",
        ),
    ),
)
def test_candidate_review_submission_rejects_contract_and_lineage_drift(
    mutator,
    expected_detail,
) -> None:
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    case = copy.deepcopy(case)
    review = copy.deepcopy(review)
    validation = copy.deepcopy(validation)
    mutator(case, review, validation)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)

    with sessions.begin() as session, pytest.raises(EosCandidateReviewError) as error:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )

    assert expected_detail in error.value.detail
    assert reviews.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)["state"] == "DRAFT"


def test_candidate_review_submission_rejects_ineligible_state_and_naive_clock() -> None:
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
    with sessions.begin() as session:
        session.execute(
            update(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == CANDIDATE_ID)
            .values(state="READY_FOR_REVIEW")
        )
    with sessions.begin() as session, pytest.raises(EosCandidateReviewError) as state:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    assert state.value.status_code == 409

    with sessions.begin() as session:
        session.execute(
            update(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == CANDIDATE_ID)
            .values(state="DRAFT")
        )
    reviews = SqlAlchemyEosCandidateReviewRepository(
        sessions,
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with sessions.begin() as session, pytest.raises(EosCandidateReviewError) as clock:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    assert clock.value.status_code == 422


def test_candidate_review_legacy_decision_and_replay_guards() -> None:
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)

    assert reviews.get(tenant_id=TENANT, candidate_id=str(uuid.uuid4())) is None
    with sessions.begin() as session:
        assert (
            reviews.require_current_review_in_session(
                session,
                tenant_id=TENANT,
                approval_case_id=REVIEW_CASE_ID,
                review=review,
            )
            is None
        )
        assert (
            reviews.return_from_rejection_in_session(
                session,
                tenant_id=TENANT,
                approval_case_id=REVIEW_CASE_ID,
                review=review,
                actor_subject_id="accountant-lead",
                reason="Legacy review has no candidate transition.",
                decided_at=NOW,
            )
            is None
        )

    with sessions.begin() as session:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    stale_review = copy.deepcopy(review)
    stale_review["candidate_hash"] = PROOF_HASH
    with sessions.begin() as session, pytest.raises(EosCandidateReviewError) as stale:
        reviews.require_current_review_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=stale_review,
        )
    assert stale.value.status_code == 409

    changed_validation = copy.deepcopy(validation)
    changed_validation["validation_hash"] = PROOF_HASH
    with sessions.begin() as session, pytest.raises(EosCandidateReviewError) as replay:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=changed_validation,
        )
    assert "replay changed immutable semantics" in replay.value.detail

    with sessions.begin() as session:
        reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason="Correct the expense evidence.",
            decided_at=NOW + timedelta(minutes=1),
        )
    with (
        sessions.begin() as session,
        pytest.raises(EosCandidateReviewError) as returned,
    ):
        reviews.return_from_rejection_in_session(
            session,
            tenant_id=TENANT,
            approval_case_id=REVIEW_CASE_ID,
            review=review,
            actor_subject_id="accountant-lead",
            reason="A different replay reason.",
            decided_at=NOW + timedelta(minutes=1),
        )
    assert "return replay changed immutable semantics" in returned.value.detail


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.pop("reason"),
        lambda value: value.update(schema_version="unsupported"),
        lambda value: value.update(tenant_id=""),
        lambda value: value.update(tenant_id="x" * 129),
        lambda value: value.update(event_id="not-a-uuid"),
        lambda value: value.update(expected_candidate_version=True),
        lambda value: value.update(expected_candidate_version=0),
        lambda value: value.update(expected_candidate_version="1"),
        lambda value: value.update(expected_candidate_hash="not-a-hash"),
        lambda value: value.update(actor_subject_id=None),
        lambda value: value.update(actor_subject_id="x" * 129),
        lambda value: value.update(reason=None),
        lambda value: value.update(reason="x" * 2001),
        lambda value: value.update(invalidated_at="not-a-date-time"),
        lambda value: value.update(invalidated_at="2026-11-12T02:00:00"),
    ),
)
def test_candidate_review_invalidation_contract_rejects_malformed_values(
    mutator,
) -> None:
    payload = _review_invalidation_payload({"candidate_hash": PROOF_HASH})
    mutator(payload)
    reviews = SqlAlchemyEosCandidateReviewRepository(None)
    with pytest.raises(EosCandidateReviewError) as error:
        reviews.invalidate(payload)
    assert error.value.status_code == 422


def test_candidate_review_invalidation_rejects_missing_stale_and_changed_replay() -> (
    None
):
    _engine_value, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    case, review, validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)

    with pytest.raises(EosCandidateReviewError) as missing:
        reviews.invalidate(
            _review_invalidation_payload(review, expected_candidate_version=1)
        )
    assert missing.value.status_code == 404

    with sessions.begin() as session:
        reviews.submit_in_session(
            session,
            scoped_case=case,
            review=review,
            validation=validation,
        )
    with pytest.raises(EosCandidateReviewError) as absent_candidate:
        reviews.invalidate(
            _review_invalidation_payload(review, candidate_id=str(uuid.uuid4()))
        )
    assert absent_candidate.value.status_code == 404
    with pytest.raises(EosCandidateReviewError) as stale:
        reviews.invalidate(
            _review_invalidation_payload(review, expected_candidate_version=3)
        )
    assert stale.value.status_code == 409

    payload = _review_invalidation_payload(review)
    reviews.invalidate(payload)
    changed_replay = dict(payload, reason="Changed replay semantics.")
    with pytest.raises(EosCandidateReviewError) as replay:
        reviews.invalidate(changed_replay)
    assert "replay changed immutable semantics" in replay.value.detail


def test_candidate_review_persistence_failures_and_cas_conflicts_are_typed(
    monkeypatch,
) -> None:
    engine, sessions, candidates, command, _authorization = _runtime()
    command.execute(_payload(), caller=CALLER)
    _case, review, _validation = _candidate_review_fixture(sessions, candidates)
    reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
    payload = _review_invalidation_payload(review)

    def raise_integrity(*_args, **_kwargs):
        raise IntegrityError("candidate review", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(reviews, "_event_by_id", raise_integrity)
    with pytest.raises(EosCandidateReviewError) as conflict:
        reviews.invalidate(payload)
    assert conflict.value.status_code == 409

    def raise_database_error(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(reviews, "_event_by_id", raise_database_error)
    with pytest.raises(EosCandidateReviewError) as unavailable:
        reviews.invalidate(payload)
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    engine.dispose()
    with pytest.raises(EosCandidateReviewError) as get_unavailable:
        reviews.get(tenant_id=TENANT, candidate_id=CANDIDATE_ID)
    assert get_unavailable.value.status_code == 503


def test_candidate_review_low_level_cas_event_and_timestamp_guards() -> None:
    class ConcurrentSession:
        def execute(self, _statement):
            return SimpleNamespace(rowcount=0)

    candidate = {
        "tenant_id": TENANT,
        "candidate_id": CANDIDATE_ID,
        "state": "DRAFT",
        "version": 1,
    }
    record = {
        "to_state": "READY_FOR_REVIEW",
        "resulting_version": 2,
        "created_at": NOW,
    }
    with pytest.raises(EosCandidateReviewError) as cas:
        SqlAlchemyEosCandidateReviewRepository._advance_candidate(
            ConcurrentSession(),
            candidate=candidate,
            record=record,
        )
    assert cas.value.status_code == 409

    class DuplicateSession:
        def execute(self, _statement):
            raise IntegrityError("candidate review", {}, RuntimeError("duplicate"))

    with pytest.raises(EosCandidateReviewError) as duplicate:
        SqlAlchemyEosCandidateReviewRepository._insert_event(DuplicateSession(), {})
    assert duplicate.value.status_code == 409

    assert candidate_review_module._review_hash(
        {"validation_observed_at": NOW.isoformat(), "candidate_id": CANDIDATE_ID}
    ).startswith("sha256:")
    assert candidate_review_module._timestamp(NOW.replace(tzinfo=None)).endswith(
        "+00:00"
    )
    with pytest.raises(EosCandidateReviewError) as timestamp:
        candidate_review_module._timestamp("not-a-timestamp")
    assert timestamp.value.status_code == 422


@pytest.mark.skipif(
    not DATABASE_URL or not REVIEW_POSTGRES_SMOKE,
    reason="Protected W30-S3-03 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_candidate_review_state_machine_and_immutability() -> None:
    schema_name = f"mybee_w30s303_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_eos_test", "nex_eos_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = (
        make_url(DATABASE_URL)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )
    engine = None
    try:
        migration = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2535_eos_candidate_review_state" in migration.applied
        engine = create_engine(scoped_url, pool_pre_ping=True)
        _engine_value, sessions, candidates, command, _authorization = _runtime(
            engine=engine
        )
        command.execute(_payload(), caller=CALLER)
        case, review, validation = _candidate_review_fixture(sessions, candidates)
        reviews = SqlAlchemyEosCandidateReviewRepository(sessions, clock=lambda: NOW)
        with sessions.begin() as session:
            reviews.submit_in_session(
                session,
                scoped_case=case,
                review=review,
                validation=validation,
            )
        with sessions.begin() as session:
            returned = reviews.return_from_rejection_in_session(
                session,
                tenant_id=TENANT,
                approval_case_id=REVIEW_CASE_ID,
                review=review,
                actor_subject_id="accountant-lead",
                reason="Return for correction.",
                decided_at=NOW + timedelta(minutes=1),
            )
        assert returned is not None
        assert returned["to_state"] == "RETURNED_FOR_CORRECTION"
        with sessions() as session:
            with pytest.raises(DBAPIError):
                session.execute(
                    update(EOS_CANDIDATE_REVIEW_EVENT_TABLE).values(reason="tampered")
                )
                session.commit()
            session.rollback()
        engine.dispose()
        engine = None
    finally:
        if engine is not None:
            engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
