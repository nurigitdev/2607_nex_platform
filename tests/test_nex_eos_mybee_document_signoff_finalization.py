from __future__ import annotations

import copy
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import nex_eos.document_signoff as document_signoff_module
import pytest
from mybee_ax.domain import BusinessProposalProjectRef, build_business_proposal_form
from mybee_ax.integrations.nex_business_approval_client import (
    build_business_proposal_approval_request,
)
from nex_eos import (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVED_DOCUMENT_TABLE,
    EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE,
    EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE,
    EOS_METADATA,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    EOS_SCOPED_APPROVAL_DECISION_TABLE,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosDocumentSignoffError,
    EosDocumentSignoffService,
    EosScopedApprovalDecisionRouter,
    EosScopedApprovalError,
    EosScopedApprovalService,
    EosServiceCaller,
    LegalEntityInput,
    NvtProjectInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    SqlAlchemyDocumentSignoffContextRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosApprovedDocumentRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosScopedApprovalRepository,
    admit_document_signoff_context,
    scoped_approval_payload_hash,
)
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import OaAuthorizationService
from nex_oa.memberships import build_tenant_membership_registry_for_runtime
from nex_oa.subjects import build_subject_registry_for_runtime
from nex_runtime import (
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
)
from nex_wc.approvals import (
    ApprovalDecisionAuthorizer,
    ApprovalDecisionService,
    ApprovalWorkItemService,
    SqlAlchemyApprovalWorkItemRepository,
)
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)
TENANT = "VO00"
COMPANY_ID = "30000000-0000-4000-8000-000000000001"
NVT_ID = "30000000-0000-4000-8000-000000000002"
PROJECT_ID = "30000000-0000-4000-8000-000000000003"
PROJECT_CODE = "VO00D260001"
POLICY_ID = "30000000-0000-4000-8000-000000000004"
CASE_ID = "30000000-0000-4000-8000-000000000005"
OPERATION_ID = "30000000-0000-4000-8000-000000000006"
HASH = "sha256:" + "a" * 64
EOS_DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
WC_DATABASE_URL = os.getenv("NEX_WC_TEST_DATABASE_URL", "")
OA_DATABASE_URL = os.getenv("NEX_OA_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_W30_S00_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.unavailable = False
        self.overrides: dict[str, object] = {}
        self.denied = False
        self.non_mapping = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("OA unavailable")
        if self.denied:
            from nex_eos import AuthorizationSubjectDenied

            raise AuthorizationSubjectDenied("revoked")
        if self.non_mapping:
            return "malformed"
        requester = subject_id == "employee-1004"
        result = {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "roles": [
                (
                    "EMPLOYEE"
                    if requester
                    else ("CEO" if subject_id == "approver-ceo" else "TEAM_LEAD")
                )
            ],
            "scopes": [
                "finance:journal:request-approval" if requester else "approval:decide"
            ],
            "company_ids": [COMPANY_ID],
            "project_ids": [PROJECT_ID],
            "revision_hash": "sha256:" + "b" * 64,
            "decision_ref": f"oa-authz:{subject_id}",
        }
        result.update(self.overrides)
        return result


class WcClient:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.fail = False
        self.malformed = False

    def create_or_get(self, value):
        if self.fail:
            raise RuntimeError("WC unavailable")
        if self.malformed:
            return {}
        item = dict(value)
        existing = self.items.setdefault(item["approval_work_item_id"], item)
        return {"work_item": dict(existing), "created": existing is item}


class AccountingService:
    def __init__(self) -> None:
        self.calls = 0

    def ingest_wc_delivery(self, delivery):
        self.calls += 1
        return {"purpose": "ACCOUNTING_POSTING", "delivery": delivery}


class RepositoryWcClient:
    def __init__(self, repository) -> None:
        self._service = ApprovalWorkItemService(repository)

    def create_or_get(self, work_item):
        return self._service.create_or_get(work_item)


class OaAuthorizationSource:
    def __init__(self, service: OaAuthorizationService) -> None:
        self._service = service

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        response = self._service.effective_authorization(
            tenant_id=tenant_id, subject_id=subject_id
        )
        authorization = response.get("authorization")
        if not isinstance(authorization, dict):
            raise TypeError("OA authorization response is invalid")
        return {**authorization, "active": True}


def _proposal():
    return build_business_proposal_form(
        tenant_id=TENANT,
        proposal_id="proposal-w30-0001",
        revision=1,
        company_id=COMPANY_ID,
        title="프로젝트 장비 구매 품의",
        purpose="개발 장비 구매",
        business_justification="프로젝트 수행에 필요한 공용 장비입니다.",
        scope_type="PROJECT",
        project_refs=(BusinessProposalProjectRef(PROJECT_ID, PROJECT_CODE),),
        requested_amount="1250000",
        currency="KRW",
        requester_subject_id="employee-1004",
        valid_from=NOW + timedelta(days=1),
        valid_until=NOW + timedelta(days=31),
        attachments=(),
    )


def _request():
    return build_business_proposal_approval_request(
        _proposal(),
        business_operation_id=OPERATION_ID,
        idempotency_key="w30-s00-proposal-r1",
        case_id=CASE_ID,
        approval_policy_id=POLICY_ID,
        correlation_id="w30-s00-correlation",
        causation_id="w30-s00-causation",
        expires_at=NOW + timedelta(hours=12),
    )


def _runtime(*, stages=("TEAM_LEAD",), engine=None, auth=None, wc=None):
    engine = engine or create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    legal = SqlAlchemyEosLegalEntityRepository(sessions)
    legal.create_legal_entity(
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
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-W30", "NVT"))
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            PROJECT_CODE,
            "W30 Project",
            nvt_project_id=NVT_ID,
        )
    )
    legal.create_project_company_binding(
        ProjectCompanyBindingInput(
            TENANT,
            str(uuid.uuid4()),
            PROJECT_ID,
            COMPANY_ID,
            date(2026, 1, 1),
            HASH,
        )
    )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="mybee.document-signoff.w30",
            name="MyBee document signoff",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            transaction_type="DOCUMENT_SIGNOFF",
            stages=tuple(ApprovalPolicyStageInput(role) for role in stages),
        )
    )
    auth = auth or AuthorizationSource()
    wc = wc or WcClient()
    scoped = EosScopedApprovalService(
        repository=SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW),
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions, clock=lambda: NOW
        ),
        authorization_source=auth,
        wc_client=wc,
        document_signoff_repository=SqlAlchemyDocumentSignoffContextRepository(
            sessions, clock=lambda: NOW
        ),
        clock=lambda: NOW,
    )
    finalizer = EosDocumentSignoffService(
        session_factory=sessions,
        authorization_source=auth,
        wc_client=wc,
        document_repository=SqlAlchemyEosApprovedDocumentRepository(
            sessions, clock=lambda: NOW + timedelta(minutes=10)
        ),
        clock=lambda: NOW + timedelta(minutes=5),
    )
    accounting = AccountingService()
    router = EosScopedApprovalDecisionRouter(
        session_factory=sessions,
        accounting_service=accounting,
        document_signoff_service=finalizer,
    )
    return sessions, scoped, finalizer, router, auth, wc, accounting


def _delivery(item, *, principal="approver-2001", decision="APPROVE", suffix="1"):
    work_item = {**item, "state": "APPROVED" if decision == "APPROVE" else "REJECTED"}
    work_item["version"] += 1
    decided_at = (NOW + timedelta(minutes=int(suffix))).isoformat()
    decision_id = str(uuid.uuid5(uuid.UUID(CASE_ID), f"decision-{suffix}"))
    event_id = str(uuid.uuid5(uuid.UUID(CASE_ID), f"event-{suffix}"))
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": str(uuid.uuid5(uuid.UUID(CASE_ID), f"outbox-{suffix}")),
        "work_item": work_item,
        "decision": {
            "schema_version": "wc_approval_decision.v1",
            "tenant_id": TENANT,
            "decision_id": decision_id,
            "approval_work_item_id": item["approval_work_item_id"],
            "decision": decision,
            "decided_by": principal,
            "decision_comment": "approved",
            "decision_version": 1,
            "authorized_by_oa": True,
            "oa_decision_ref": "oa-wc:w30",
            "authorization_revision_hash": "sha256:" + "c" * 64,
            "authorization_checked_at": decided_at,
            "decided_at": decided_at,
        },
        "event": {
            "schema_version": "wc_approval_event.v1",
            "tenant_id": TENANT,
            "event_id": event_id,
            "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
            "approval_work_item_id": item["approval_work_item_id"],
            "decision_id": decision_id,
            "approval_domain": "BUSINESS_FORMAL",
            "decision": decision,
            "decided_by": principal,
            "oa_decision_ref": "oa-wc:w30",
            "occurred_at": decided_at,
            "correlation_id": f"w30-correlation-{suffix}",
            "causation_id": f"w30-causation-{suffix}",
        },
    }


def _create_case(scoped):
    return scoped.request_case(
        _request().payload,
        caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
    )


def test_migration_and_request_contract_freeze_document_context_before_decision():
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2530_eos_document_signoff_finalization"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_document_signoff_context" in compact
    assert "create table if not exists eos_document_signoff_evidence" in compact
    assert "ck_eos_approved_doc_proof_source" in compact
    assert "eos_reject_document_signoff_mutation" in compact
    attribution_migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2533_eos_mandatory_project_attribution"
    )
    attribution_sql = " ".join(attribution_migration.sql.lower().split())
    assert "allowed_project_codes jsonb not null" in attribution_sql
    context = _request().payload["case"]["document_signoff_context"]
    assert context["approved_document_id"] == "proposal-w30-0001"
    assert context["subject_hash"] == _proposal().approval_subject_hash
    assert context["allowed_project_codes"] == [PROJECT_CODE]
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE,
            EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE,
            EOS_APPROVED_DOCUMENT_TABLE,
        )
        for constraint in table.constraints
    )


def test_terminal_approval_materializes_exact_evidence_and_envelope_once():
    sessions, scoped, _finalizer, router, _auth, wc, accounting = _runtime()
    receipt = _create_case(scoped)
    item = receipt["wc_publication"]["work_item"]
    assert '"document_signoff":' in item["display_safe_summary"]
    assert item["target_role_ref"] == "TEAM_LEAD"
    assert item["target_project_scope_ref"] is None
    delivery = _delivery(item)
    result = router.ingest_wc_delivery(delivery)
    assert result["purpose"] == "DOCUMENT_SIGNOFF"
    assert result["case_state"] == "APPROVED"
    assert result["document_signoff_evidence"]["proof_hash"].startswith("sha256:")
    envelope = result["approved_document_envelope"]
    assert envelope["schema_version"] == "eos_approved_document_envelope.v2"
    assert envelope["approved_document_id"] == "proposal-w30-0001"
    assert envelope["allowed_project_ids"] == [PROJECT_ID]
    assert envelope["allowed_project_codes"] == [PROJECT_CODE]
    assert (
        envelope["business_approval_proof_id"]
        == result["document_signoff_evidence"]["evidence_id"]
    )
    assert envelope["approved_amount"] == "1250000.0000"
    replay = router.ingest_wc_delivery(delivery)
    assert replay["created"] is False
    assert replay["approved_document_envelope"] == envelope
    assert accounting.calls == 0
    assert len(wc.items) == 1
    with sessions() as session:
        for table in (
            EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE,
            EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE,
            EOS_SCOPED_APPROVAL_DECISION_TABLE,
            EOS_APPROVED_DOCUMENT_TABLE,
        ):
            assert session.scalar(select(func.count()).select_from(table)) == 1


def test_project_code_mismatch_rolls_back_case_and_document_context():
    sessions, scoped, _finalizer, _router, _auth, _wc, _accounting = _runtime()
    payload = copy.deepcopy(dict(_request().payload))
    payload["case"]["document_signoff_context"]["allowed_project_codes"] = [
        "VO00D260999"
    ]
    payload["payload_hash"] = scoped_approval_payload_hash(payload)

    with pytest.raises(EosScopedApprovalError) as error:
        scoped.request_case(
            payload,
            caller=EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",)),
        )
    assert error.value.error_code == "EOS_DOCUMENT_SIGNOFF_CONFLICT"
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_CASE_TABLE)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE)
            )
            == 0
        )


def test_reject_creates_no_evidence_or_envelope():
    sessions, scoped, _finalizer, router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    result = router.ingest_wc_delivery(_delivery(item, decision="REJECT"))
    assert result["case_state"] == "REJECTED"
    assert result["document_signoff_evidence"] is None
    assert result["approved_document_envelope"] is None
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_APPROVED_DOCUMENT_TABLE)
            )
            == 0
        )


def test_two_stage_signoff_publishes_next_stage_then_materializes():
    _sessions, scoped, _finalizer, router, _auth, _wc, _accounting = _runtime(
        stages=("TEAM_LEAD", "CEO")
    )
    first_item = _create_case(scoped)["wc_publication"]["work_item"]
    first = router.ingest_wc_delivery(
        _delivery(first_item, principal="approver-2001", suffix="1")
    )
    assert first["case_state"] == "PENDING"
    assert first["document_signoff_evidence"] is None
    next_item = first["next_stage_publication"]["work_item"]
    assert next_item["target_role_ref"] == "CEO"
    final = router.ingest_wc_delivery(
        _delivery(next_item, principal="approver-ceo", suffix="2")
    )
    assert final["case_state"] == "APPROVED"
    assert final["approved_document_envelope"]["state"] == "ACTIVE"
    assert final["approved_document_envelope"]["usable"] is False


def test_context_replay_is_stable_and_semantic_drift_conflicts():
    sessions, scoped, _finalizer, _router, _auth, _wc, _accounting = _runtime()
    _create_case(scoped)
    repository = SqlAlchemyDocumentSignoffContextRepository(sessions, clock=lambda: NOW)
    with sessions() as session:
        case = dict(
            session.execute(
                select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
                    EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID
                )
            )
            .mappings()
            .one()
        )
        case["project_ids"] = [PROJECT_ID]
        context = dict(_request().payload["case"]["document_signoff_context"])
        replay = repository.create_in_session(
            session, scoped_case=case, context=context
        )
        assert replay["context_hash"].startswith("sha256:")
        context["approved_amount"] = "1250001.0000"
        with pytest.raises(EosDocumentSignoffError) as conflict:
            repository.create_in_session(session, scoped_case=case, context=context)
        assert conflict.value.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", "wrong"),
        ("envelope_id", "bad"),
        ("approved_document_id", " bad"),
        ("document_revision", 0),
        ("document_revision", 2),
        ("document_type", " bad"),
        ("work_code", "BAD"),
        ("document_content_hash", "bad"),
        ("approved_amount", "0"),
        ("approved_amount", "1.00001"),
        ("approved_currency", "krw"),
        ("valid_from", "bad"),
        ("valid_until", "2026-11-11T00:00:00Z"),
        ("subject_hash", "sha256:" + "f" * 64),
    ),
)
def test_context_contract_rejects_malformed_or_unbound_values(field, value):
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    context[field] = value
    with pytest.raises(EosDocumentSignoffError) as error:
        admit_document_signoff_context(context, scoped_case=case)
    assert error.value.status_code == 422


def test_context_contract_rejects_field_drift_wrong_purpose_and_naive_time():
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    with pytest.raises(EosDocumentSignoffError):
        admit_document_signoff_context({**context, "extra": True}, scoped_case=case)
    case["purpose"] = "ACCOUNTING_POSTING"
    with pytest.raises(EosDocumentSignoffError):
        admit_document_signoff_context(context, scoped_case=case)


def test_context_contract_rejects_non_mapping_payload() -> None:
    case = dict(_request().payload["case"])
    case.pop("document_signoff_context")

    with pytest.raises(EosDocumentSignoffError) as error:
        admit_document_signoff_context(None, scoped_case=case)  # type: ignore[arg-type]

    assert error.value.status_code == 422


def test_context_contract_preserves_v1_read_compatibility() -> None:
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    context["schema_version"] = "eos_document_signoff_context.v1"
    context.pop("allowed_project_codes")

    admitted = admit_document_signoff_context(context, scoped_case=case)

    assert "allowed_project_codes" not in admitted
    assert admitted["context_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    "project_codes",
    (
        None,
        "VO00D260001",
        [],
        ["VO00D260001", "VO00D260001"],
        ["VO00R260001"],
    ),
)
def test_context_v2_rejects_malformed_project_code_collections(project_codes) -> None:
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    context["allowed_project_codes"] = project_codes

    with pytest.raises(EosDocumentSignoffError) as error:
        admit_document_signoff_context(context, scoped_case=case)

    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("case_overrides", "project_codes"),
    (
        ({"scope_type": "COMPANY", "project_ids": []}, [PROJECT_CODE]),
        ({}, [PROJECT_CODE, "VO00D260002"]),
        ({}, ["OTHRD260001"]),
    ),
)
def test_context_v2_requires_codes_for_exact_non_company_tenant_scope(
    case_overrides, project_codes
) -> None:
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    case.update(case_overrides)
    context["allowed_project_codes"] = project_codes

    with pytest.raises(EosDocumentSignoffError) as error:
        admit_document_signoff_context(context, scoped_case=case)

    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("approved_amount", object()),
        ("valid_from", 1),
        ("valid_from", "2026-11-12T06:00:00"),
    ),
)
def test_context_contract_rejects_non_decimal_and_non_aware_time(field, value):
    case = dict(_request().payload["case"])
    context = dict(case.pop("document_signoff_context"))
    context[field] = value
    with pytest.raises(EosDocumentSignoffError) as error:
        admit_document_signoff_context(context, scoped_case=case)
    assert error.value.status_code == 422


def test_context_repository_rejects_non_datetime_clock():
    sessions, scoped, _finalizer, _router, _auth, _wc, _accounting = _runtime()
    _create_case(scoped)
    repository = SqlAlchemyDocumentSignoffContextRepository(
        sessions, clock=lambda: "not-a-datetime"
    )
    with sessions() as session:
        case = dict(
            session.execute(
                select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
                    EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID
                )
            )
            .mappings()
            .one()
        )
        case["project_ids"] = [PROJECT_ID]
        with pytest.raises(EosDocumentSignoffError) as error:
            repository.create_in_session(
                session,
                scoped_case=case,
                context=_request().payload["case"]["document_signoff_context"],
            )
    assert error.value.status_code == 422


def test_router_preserves_accounting_path_and_missing_case_fails_closed():
    sessions, scoped, _finalizer, router, _auth, _wc, accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
            .values(purpose="ACCOUNTING_POSTING")
        )
    routed = router.ingest_wc_delivery(_delivery(item))
    assert routed["purpose"] == "ACCOUNTING_POSTING"
    assert accounting.calls == 1

    missing = _delivery(item, suffix="9")
    missing_id = str(uuid.uuid4())
    missing["work_item"]["resume_target_ref"] = (
        f"eos.scoped-approval-case:{missing_id}:stage:1"
    )
    with pytest.raises(EosDocumentSignoffError) as error:
        router.ingest_wc_delivery(missing)
    assert error.value.status_code == 404


def test_missing_context_and_invalid_delivery_fail_closed():
    sessions, scoped, finalizer, router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            delete(EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE).where(
                EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.c.case_id == CASE_ID
            )
        )
    with pytest.raises(EosDocumentSignoffError) as missing:
        finalizer.ingest_wc_delivery(_delivery(item))
    assert missing.value.status_code == 409
    with pytest.raises(EosDocumentSignoffError) as invalid:
        router.ingest_wc_delivery({})
    assert invalid.value.status_code == 422
    with pytest.raises(EosDocumentSignoffError) as direct_invalid:
        finalizer.ingest_wc_delivery({})
    assert direct_invalid.value.status_code == 422


def test_direct_finalizer_missing_case_fails_closed():
    _sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    missing = _delivery(item, suffix="9")
    missing_id = str(uuid.uuid4())
    missing["work_item"]["resume_target_ref"] = (
        f"eos.scoped-approval-case:{missing_id}:stage:1"
    )
    with pytest.raises(EosDocumentSignoffError) as error:
        finalizer.ingest_wc_delivery(missing)
    assert error.value.status_code == 404


def test_missing_next_policy_stage_and_terminal_case_fail_closed():
    sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime(
        stages=("TEAM_LEAD", "CEO")
    )
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            delete(EOS_APPROVAL_POLICY_STAGE_TABLE).where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == 2,
            )
        )
    with pytest.raises(EosDocumentSignoffError) as missing_stage:
        finalizer.ingest_wc_delivery(_delivery(item))
    assert missing_stage.value.status_code == 409

    sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
            .values(state="REJECTED")
        )
    with pytest.raises(EosDocumentSignoffError) as terminal:
        finalizer.ingest_wc_delivery(_delivery(item))
    assert terminal.value.status_code == 409


def test_router_unknown_purpose_and_database_failure_fail_closed():
    sessions, scoped, _finalizer, router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(text("PRAGMA ignore_check_constraints = ON"))
        session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
            .values(purpose="UNKNOWN")
        )
    with pytest.raises(EosDocumentSignoffError) as unknown:
        router.ingest_wc_delivery(_delivery(item))
    assert unknown.value.status_code == 409

    class BrokenSession:
        def __enter__(self):
            raise SQLAlchemyError("database unavailable")

        def __exit__(self, *_args):
            return False

    router._session_factory = lambda: BrokenSession()
    with pytest.raises(EosDocumentSignoffError) as unavailable:
        router.ingest_wc_delivery(_delivery(item))
    assert unavailable.value.status_code == 503


def test_transaction_race_reuses_matching_decision_without_duplicate(
    monkeypatch,
):
    _sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    calls = 0

    def racing_decision_lookup(_session, admitted):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return {"decision_hash": admitted["decision_hash"]}

    monkeypatch.setattr(
        document_signoff_module,
        "_load_decision_by_identity",
        racing_decision_lookup,
    )
    result = finalizer.ingest_wc_delivery(_delivery(item))
    assert result["created"] is False
    assert result["case_state"] == "PENDING"
    assert calls == 2


@pytest.mark.parametrize("mode", ("replay", "transaction", "state"))
def test_database_failures_map_to_retryable_unavailable(mode, monkeypatch):
    _sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]

    class BrokenContext:
        def __enter__(self):
            raise SQLAlchemyError("database unavailable")

        def __exit__(self, *_args):
            return False

    class BrokenFactory:
        def __call__(self):
            return BrokenContext()

        def begin(self):
            return BrokenContext()

    finalizer._session_factory = BrokenFactory()
    if mode == "transaction":
        monkeypatch.setattr(finalizer, "_load_replay", lambda _admitted: None)
        call = lambda: finalizer.ingest_wc_delivery(_delivery(item))
    elif mode == "state":
        call = lambda: finalizer._load_state({"tenant_id": TENANT, "case_id": CASE_ID})
    else:
        call = lambda: finalizer.ingest_wc_delivery(_delivery(item))
    with pytest.raises(EosDocumentSignoffError) as error:
        call()
    assert error.value.status_code == 503
    assert error.value.retryable is True


def test_state_read_for_missing_case_fails_closed():
    _sessions, _scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    with pytest.raises(EosDocumentSignoffError) as error:
        finalizer._load_state({"tenant_id": TENANT, "case_id": str(uuid.uuid4())})
    assert error.value.status_code == 404


@pytest.mark.parametrize("mode", ("expired", "semantic", "wrong_purpose"))
def test_persisted_case_and_wc_binding_drift_fail_closed(mode):
    sessions, scoped, finalizer, _router, _auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item)
    if mode == "semantic":
        delivery["work_item"]["semantic_hash"] = "sha256:" + "f" * 64
    else:
        values = (
            {"expires_at": NOW}
            if mode == "expired"
            else {"purpose": "ACCOUNTING_POSTING"}
        )
        with sessions.begin() as session:
            session.execute(
                update(EOS_SCOPED_APPROVAL_CASE_TABLE)
                .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
                .values(**values)
            )
    with pytest.raises(EosDocumentSignoffError) as error:
        finalizer.ingest_wc_delivery(delivery)
    assert error.value.status_code == 409


def test_changed_replay_and_fresh_oa_error_shapes_fail_closed():
    _sessions, scoped, _finalizer, router, auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item)
    router.ingest_wc_delivery(delivery)
    changed = _delivery(item)
    changed["decision"]["decision_comment"] = "changed"
    with pytest.raises(EosDocumentSignoffError) as conflict:
        router.ingest_wc_delivery(changed)
    assert conflict.value.status_code == 409

    _sessions, scoped, _finalizer, router, auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.denied = True
    with pytest.raises(EosDocumentSignoffError) as denied:
        router.ingest_wc_delivery(_delivery(item))
    assert denied.value.status_code == 403
    auth.denied = False
    auth.non_mapping = True
    with pytest.raises(EosDocumentSignoffError) as malformed:
        router.ingest_wc_delivery(_delivery(item))
    assert malformed.value.status_code == 403


def test_bare_oa_revision_digest_is_normalized_in_persisted_evidence():
    _sessions, scoped, _finalizer, router, auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.overrides = {"revision_hash": "b" * 64}
    result = router.ingest_wc_delivery(_delivery(item))
    assert (
        result["document_signoff_evidence"]["oa_authorization_revision_hash"]
        == "sha256:" + "b" * 64
    )


@pytest.mark.parametrize("mode", ("unavailable", "malformed"))
def test_next_stage_wc_recovery_fails_closed_after_committed_decision(mode):
    _sessions, scoped, _finalizer, router, _auth, wc, _accounting = _runtime(
        stages=("TEAM_LEAD", "CEO")
    )
    item = _create_case(scoped)["wc_publication"]["work_item"]
    setattr(wc, "fail" if mode == "unavailable" else "malformed", True)
    with pytest.raises(EosDocumentSignoffError) as error:
        router.ingest_wc_delivery(_delivery(item))
    assert error.value.status_code in {409, 503}
    assert error.value.retryable is True


@pytest.mark.parametrize(
    "overrides",
    (
        {"tenant_id": "other"},
        {"subject_id": "other"},
        {"scopes": []},
        {"scopes": ["approval:read"]},
        {"roles": ["EMPLOYEE"]},
        {"company_ids": [str(uuid.uuid4())]},
        {"revision_hash": "bad"},
        {"scopes": "approval:decide"},
    ),
)
def test_document_approver_current_authority_shape_fails_closed(overrides):
    _sessions, scoped, _finalizer, router, auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.overrides = overrides
    with pytest.raises(EosDocumentSignoffError) as error:
        router.ingest_wc_delivery(_delivery(item))
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "mode", ("requester", "revoked", "unavailable", "out_of_order")
)
def test_fresh_authority_sod_and_order_fail_closed(mode):
    sessions, scoped, _finalizer, router, auth, _wc, _accounting = _runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    principal = "employee-1004" if mode == "requester" else "approver-2001"
    delivery = _delivery(item, principal=principal)
    if mode == "revoked":
        auth.active = False
    elif mode == "unavailable":
        auth.unavailable = True
    elif mode == "out_of_order":
        delivery["work_item"]["version"] += 1
    with pytest.raises(EosDocumentSignoffError) as error:
        router.ingest_wc_delivery(delivery)
    assert error.value.status_code in {403, 409, 503}
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_APPROVED_DOCUMENT_TABLE)
            )
            == 0
        )


def test_source_files_document_the_closed_w30_boundary():
    source = Path("services/nex-eos/nex_eos/document_signoff.py").read_text(
        encoding="utf-8"
    )
    assert "DOCUMENT_SIGNOFF" in source
    assert "ACCOUNTING_POSTING cannot satisfy document signoff" in source
    assert "approval:decide" in source


def _scoped_database_url(database_url: str, schema_name: str) -> str:
    return (
        make_url(database_url)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )


def _dispose_oa_runtime(runtime) -> None:
    if (
        runtime.worker_engine is not None
        and runtime.worker_engine is not runtime.api_engine
    ):
        runtime.worker_engine.dispose()
    if runtime.api_engine is not None:
        runtime.api_engine.dispose()


@pytest.mark.skipif(
    not EOS_DATABASE_URL
    or not WC_DATABASE_URL
    or not OA_DATABASE_URL
    or not POSTGRES_SMOKE,
    reason="Protected W30-S00 EOS/WC/OA PostgreSQL smoke is disabled",
)
def test_actual_eos_wc_oa_postgres_document_signoff_replay_and_zero_residue():
    suffix = uuid.uuid4().hex
    targets = {
        "nex-eos": (EOS_DATABASE_URL, f"w30_s00_eos_{suffix}"),
        "nex-wc": (WC_DATABASE_URL, f"w30_s00_wc_{suffix}"),
        "nex-oa": (OA_DATABASE_URL, f"w30_s00_oa_{suffix}"),
    }
    base_engines = {
        service_id: create_engine(database_url, pool_pre_ping=True)
        for service_id, (database_url, _schema) in targets.items()
    }
    scoped_urls = {
        service_id: _scoped_database_url(database_url, schema)
        for service_id, (database_url, schema) in targets.items()
    }
    eos_engine = wc_engine = None
    oa_runtime = None
    try:
        for service_id, engine in base_engines.items():
            schema = targets[service_id][1]
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        for service_id, database_url in scoped_urls.items():
            result = run_service_migrations(
                service_id, database_url=database_url, profile="test"
            )
            assert len(result.planned) == len(result.applied) + len(result.skipped)

        eos_engine = create_engine(scoped_urls["nex-eos"], pool_pre_ping=True)
        wc_engine = create_engine(scoped_urls["nex-wc"], pool_pre_ping=True)
        wc_sessions = sessionmaker(
            bind=wc_engine, autoflush=False, expire_on_commit=False
        )
        oa_spec = SERVICE_SPECS["nex-oa"]
        oa_runtime = attach_service_persistence_runtime(
            build_service_app(oa_spec),
            oa_spec,
            environ={
                oa_spec.database_env: scoped_urls["nex-oa"],
                "NEX_OA_PERSISTENCE_MODE": "postgres",
            },
        )
        subjects = build_subject_registry_for_runtime(oa_runtime)
        memberships = build_tenant_membership_registry_for_runtime(
            oa_runtime, subject_registry=subjects
        )
        authorization_repository = build_authorization_repository_for_runtime(
            oa_runtime
        )
        authorization_source = OaAuthorizationSource(
            OaAuthorizationService(
                repository=authorization_repository,
                resolver=OaEffectiveAuthorizationResolver(authorization_repository),
                membership_registry=memberships,
            )
        )
        memberships.ensure_membership(
            {
                "tenant_id": TENANT,
                "subject_id": "employee-1004",
                "tenant_display_name": "W30 S00 Tenant",
                "subject_display_name": "Employee 1004",
                "roles": ["EMPLOYEE"],
                "scopes": ["finance:journal:request-approval"],
                "membership_metadata": {"smoke_marker": "w30-s00"},
            }
        )
        memberships.ensure_membership(
            {
                "tenant_id": TENANT,
                "subject_id": "approver-2001",
                "tenant_display_name": "W30 S00 Tenant",
                "subject_display_name": "Approver 2001",
                "roles": ["TEAM_LEAD"],
                "scopes": ["approval:decide"],
                "membership_metadata": {"smoke_marker": "w30-s00"},
            }
        )
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_sessions)
        sessions, scoped, _finalizer, router, _auth, _wc, _accounting = _runtime(
            engine=eos_engine,
            auth=authorization_source,
            wc=RepositoryWcClient(wc_repository),
        )
        item = _create_case(scoped)["wc_publication"]["work_item"]
        decision_service = ApprovalDecisionService(
            wc_repository,
            authorizer=ApprovalDecisionAuthorizer(
                authorization_source, clock=lambda: NOW + timedelta(minutes=1)
            ),
            id_factory=lambda: "30000000-0000-4000-8001-000000000001",
            event_id_factory=lambda: "30000000-0000-4000-8002-000000000001",
            outbox_id_factory=lambda: "30000000-0000-4000-8003-000000000001",
            clock=lambda: NOW + timedelta(minutes=1),
        )
        decision_result = decision_service.decide(
            tenant_id=TENANT,
            approval_work_item_id=item["approval_work_item_id"],
            decision="APPROVE",
            decided_by="approver-2001",
            decision_comment="W30-S00 protected approval",
            correlation_id="w30-s00-pg-correlation",
            causation_id="w30-s00-pg-causation",
        )
        terminal_item = wc_repository.get(
            tenant_id=TENANT,
            approval_work_item_id=item["approval_work_item_id"],
        )
        pending = wc_repository.list_pending_approval_events(limit=10)
        outbox = next(
            row
            for row in pending
            if row["decision_id"] == decision_result["decision"]["decision_id"]
        )
        delivery = {
            "schema_version": "wc_approval_delivery.v1",
            "outbox_id": outbox["outbox_id"],
            "work_item": terminal_item,
            "decision": decision_result["decision"],
            "event": outbox["event_payload"],
        }
        first = router.ingest_wc_delivery(delivery)
        replay = router.ingest_wc_delivery(delivery)
        assert first["case_state"] == "APPROVED"
        assert replay["created"] is False
        assert (
            replay["approved_document_envelope"] == first["approved_document_envelope"]
        )
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(
                        EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE
                    )
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_APPROVED_DOCUMENT_TABLE)
                )
                == 1
            )
        with eos_engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = "
                        "'2530_eos_document_signoff_finalization'"
                    )
                ).scalar_one()
                == 1
            )
        with pytest.raises(DBAPIError), eos_engine.begin() as connection:
            connection.execute(
                EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.update()
                .where(EOS_DOCUMENT_SIGNOFF_CONTEXT_TABLE.c.tenant_id == TENANT)
                .values(approved_amount="1.0000")
            )
        with pytest.raises(DBAPIError), eos_engine.begin() as connection:
            connection.execute(
                EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.delete().where(
                    EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.c.tenant_id == TENANT
                )
            )
        identities = {}
        for service_id, engine in base_engines.items():
            with engine.connect() as connection:
                identities[service_id] = tuple(
                    connection.execute(
                        text("SELECT current_database(), current_user")
                    ).one()
                )
        assert identities == {
            "nex-eos": ("nex_eos_test", "nex_eos_user"),
            "nex-wc": ("nex_wc_test", "nex_wc_user"),
            "nex-oa": ("nex_oa_test", "nex_oa_user"),
        }
    finally:
        if wc_engine is not None:
            wc_engine.dispose()
        if eos_engine is not None:
            eos_engine.dispose()
        if oa_runtime is not None:
            _dispose_oa_runtime(oa_runtime)
        for service_id, engine in base_engines.items():
            schema = targets[service_id][1]
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            engine.dispose()
