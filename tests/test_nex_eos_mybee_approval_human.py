from __future__ import annotations

import os
import uuid
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import nex_eos.accounting_approval as accounting_approval_module
import psycopg
import pytest
from fastapi.testclient import TestClient
from mybee_ax.domain import AccountingSignoffViewError, accounting_signoff_view
from mybee_ax.integrations.nex_approval_client import build_scoped_approval_request
from nex_eos import (
    EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE,
    EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
    EOS_METADATA,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    EOS_SCOPED_APPROVAL_DECISION_TABLE,
    ApprovalPolicyInput,
    ApprovalPolicyStageInput,
    EosAccountingApprovalError,
    EosAccountingApprovalService,
    EosScopedApprovalError,
    EosScopedApprovalService,
    EosServiceCaller,
    LegalEntityInput,
    NvtProjectInput,
    ProjectCompanyBindingInput,
    ProjectInput,
    SqlAlchemyAccountingReviewContextRepository,
    SqlAlchemyEosApprovalPolicyRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosScopedApprovalRepository,
    accounting_review_hash,
    create_eos_app,
    scoped_approval_payload_hash,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, delete, func, make_url, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 11, 5, 0, tzinfo=UTC)
TENANT = "tenant-s2-03"
COMPANY_ID = "23000000-0000-4000-8000-000000000001"
NVT_ID = "23000000-0000-4000-8000-000000000002"
PROJECT_ID = "23000000-0000-4000-8000-000000000003"
POLICY_ID = "23000000-0000-4000-8000-000000000004"
CASE_ID = "23000000-0000-4000-8000-000000000005"
OPERATION_ID = "23000000-0000-4000-8000-000000000006"
CANDIDATE_ID = "23000000-0000-4000-8000-000000000007"
PERIOD_ID = "23000000-0000-4000-8000-000000000008"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
AUTH_HASH = "e" * 64
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S2_03_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.overrides: dict[str, object] = {}
        self.denied = False
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.denied:
            from nex_eos import AuthorizationSubjectDenied

            raise AuthorizationSubjectDenied("revoked")
        if self.unavailable:
            raise RuntimeError("OA unavailable")
        roles = {
            "employee-requester": ["EMPLOYEE"],
            "accountant-lead": ["TEAM_LEAD"],
            "accountant-ceo": ["CEO"],
            "candidate-preparer": ["TEAM_LEAD"],
            "business-approver": ["TEAM_LEAD"],
        }.get(subject_id, ["TEAM_LEAD"])
        scopes = (
            ["finance:journal:request-approval"]
            if subject_id == "employee-requester"
            else ["finance:journal:approve"]
        )
        result = {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "roles": roles,
            "scopes": scopes,
            "company_ids": [COMPANY_ID],
            "revision_hash": AUTH_HASH,
            "decision_ref": f"oa-authz:{subject_id}",
        }
        result.update(self.overrides)
        return result


class WcClient:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.fail = False
        self.response_override = None

    def create_or_get(self, work_item):
        if self.fail:
            raise RuntimeError("WC unavailable")
        if self.response_override is not None:
            return self.response_override(work_item)
        item = dict(work_item)
        existing = self.items.get(item["approval_work_item_id"])
        created = existing is None
        if existing is None:
            self.items[item["approval_work_item_id"]] = item
            existing = item
        return {"work_item": dict(existing), "created": created}


def _review(**overrides):
    value = {
        "schema_version": "eos_accounting_review_context.v2",
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_hash": HASH_A,
        "document_envelope_hash": HASH_B,
        "fx_rate_set_hash": HASH_C,
        "rule_release_hash": HASH_D,
        "accounting_period_id": PERIOD_ID,
        "candidate_preparer_subject_id": "candidate-preparer",
        "business_approver_subject_ids": ["business-approver"],
        "original_currency": "USD",
        "original_amount": "10000.00",
        "market_base_rate": "1350.20",
        "rate_reference_date": "2026-11-10",
        "rate_publication": "SMBS:2026-11-10:USD/KRW",
        "functional_currency": "KRW",
        "functional_amount": "13502000.00",
        "fx_exception": None,
    }
    value.update(overrides)
    return value


def _build_runtime(
    *, engine=None, stages=("TEAM_LEAD", "CEO"), candidate_review_repository=None
):
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
    projects.create_nvt_project(NvtProjectInput(TENANT, NVT_ID, "NVT-S203", "NVT"))
    projects.create_project(
        ProjectInput(
            TENANT, PROJECT_ID, "PROJECT-S203", "Project S2-03", nvt_project_id=NVT_ID
        )
    )
    legal.create_project_company_binding(
        ProjectCompanyBindingInput(
            TENANT,
            str(uuid.uuid4()),
            PROJECT_ID,
            COMPANY_ID,
            date(2026, 1, 1),
            HASH_C,
        )
    )
    SqlAlchemyEosApprovalPolicyRepository(sessions).create_policy(
        ApprovalPolicyInput(
            tenant_id=TENANT,
            approval_policy_id=POLICY_ID,
            policy_key="mybee.accounting.s2-03",
            name="MyBee accounting Human approval",
            approval_domain="BUSINESS_FORMAL",
            effective_from=NOW - timedelta(days=1),
            transaction_type="ACCOUNTING_POSTING",
            stages=tuple(ApprovalPolicyStageInput(item) for item in stages),
        )
    )
    auth = AuthorizationSource()
    wc = WcClient()
    context_repository = SqlAlchemyAccountingReviewContextRepository(
        sessions, clock=lambda: NOW
    )
    scoped_service = EosScopedApprovalService(
        repository=SqlAlchemyEosScopedApprovalRepository(sessions, clock=lambda: NOW),
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            sessions, clock=lambda: NOW
        ),
        authorization_source=auth,
        wc_client=wc,
        accounting_review_repository=context_repository,
        clock=lambda: NOW,
    )
    decision_service = EosAccountingApprovalService(
        session_factory=sessions,
        authorization_source=auth,
        wc_client=wc,
        candidate_review_repository=candidate_review_repository,
        clock=lambda: NOW + timedelta(minutes=5),
    )
    return sessions, scoped_service, decision_service, auth, wc


def _request(*, case_id=CASE_ID, operation_id=OPERATION_ID, review=None):
    return build_scoped_approval_request(
        tenant_id=TENANT,
        business_operation_id=operation_id,
        idempotency_key=f"s2-03-{case_id}",
        case_id=case_id,
        company_id=COMPANY_ID,
        purpose="ACCOUNTING_POSTING",
        scope_type="PROJECT",
        project_ids=[PROJECT_ID],
        subject_ref=f"eos.voucher-candidate:{CANDIDATE_ID}",
        subject_revision=1,
        subject_hash=HASH_A,
        requester_subject_id="employee-requester",
        approval_policy_id=POLICY_ID,
        correlation_id="s2-03-correlation",
        causation_id="s2-03-causation",
        accounting_review=_review() if review is None else review,
        expires_at=NOW + timedelta(days=1),
    )


def _caller():
    return EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))


def _delivery(item, *, decided_by, decision="APPROVE", suffix="1"):
    work_item = dict(item)
    work_item["state"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
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
            "approval_work_item_id": work_item["approval_work_item_id"],
            "decision": decision,
            "decided_by": decided_by,
            "decision_comment": f"decision {suffix}",
            "decision_version": 1,
            "authorized_by_oa": True,
            "oa_decision_ref": f"oa-wc:{suffix}",
            "authorization_revision_hash": "sha256:" + "f" * 64,
            "authorization_checked_at": decided_at,
            "decided_at": decided_at,
        },
        "event": {
            "schema_version": "wc_approval_event.v1",
            "tenant_id": TENANT,
            "event_id": event_id,
            "event_type": "BUSINESS_FORMAL_APPROVAL_DECIDED",
            "approval_work_item_id": work_item["approval_work_item_id"],
            "decision_id": decision_id,
            "approval_domain": "BUSINESS_FORMAL",
            "decision": decision,
            "decided_by": decided_by,
            "oa_decision_ref": f"oa-wc:{suffix}",
            "occurred_at": decided_at,
            "correlation_id": f"correlation-{suffix}",
            "causation_id": f"causation-{suffix}",
        },
    }


def _create_case(scoped_service):
    return scoped_service.request_case(_request().payload, caller=_caller())


def test_s2_03_migration_contract_and_review_identity() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2528_eos_accounting_approval_human"
    )
    compact = " ".join(migration.sql.lower().split())
    for table in (
        "eos_acct_approval_context",
        "eos_scoped_approval_decision",
        "eos_accounting_approval_evidence",
    ):
        assert f"create table if not exists {table}" in compact
    assert "eos_reject_accounting_approval_mutation" in compact
    assert accounting_review_hash(_review()).startswith("sha256:")
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (
            EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE,
            EOS_SCOPED_APPROVAL_DECISION_TABLE,
            EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE,
        )
        for constraint in table.constraints
    )
    openapi = Path("contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    assert "AccountingReviewContext:" in openapi
    assert "finance:journal:approve" in Path(
        "docs/transition/MyBee_Phase1/NeX_MyBee_D04_D12_EOS_SRS_v1.0.md"
    ).read_text(encoding="utf-8")


def test_two_stage_human_decision_creates_exact_evidence_and_replays() -> None:
    sessions, scoped, decisions, _auth, wc = _build_runtime()
    request_receipt = _create_case(scoped)
    first_item = request_receipt["wc_publication"]["work_item"]
    summary = first_item["display_safe_summary"]
    assert '"market_base_rate":"1350.20"' in summary
    assert '"functional_amount":"13502000.00"' in summary

    first_delivery = _delivery(first_item, decided_by="accountant-lead", suffix="1")
    first = decisions.ingest_wc_delivery(first_delivery)
    assert first["created"] is True
    assert first["case_state"] == "PENDING"
    assert first["accounting_approval_evidence"] is None
    next_item = first["next_stage_publication"]["work_item"]
    assert next_item["target_role_ref"] == "CEO"

    second_delivery = _delivery(next_item, decided_by="accountant-ceo", suffix="2")
    final = decisions.ingest_wc_delivery(second_delivery)
    assert final["case_state"] == "APPROVED"
    assert final["observation_state"] == "ACCOUNTING_APPROVED_PENDING_POST"
    assert final["next_stage_publication"] is None
    evidence = final["accounting_approval_evidence"]
    assert evidence["candidate_id"] == CANDIDATE_ID
    assert evidence["candidate_hash"] == HASH_A
    assert evidence["approver_subject_id"] == "accountant-ceo"
    assert (
        evidence["wc_final_decision_id"] == second_delivery["decision"]["decision_id"]
    )
    assert evidence["proof_hash"].startswith("sha256:")
    view = accounting_signoff_view(evidence)
    assert view["state"] == "ACCOUNTING_APPROVED_PENDING_POST"
    assert "oa_authorization_revision_hash" not in view

    replay = decisions.ingest_wc_delivery(second_delivery)
    assert replay["created"] is False
    assert replay["accounting_approval_evidence"] == evidence
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_DECISION_TABLE)
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE)
            )
            == 1
        )
    assert len(wc.items) == 2


def test_candidate_review_rejection_hook_is_transactional_and_replay_safe() -> None:
    class CandidateReviewSpy:
        def __init__(self) -> None:
            self.current_calls = []
            self.return_calls = []

        def require_current_review_in_session(self, _session, **kwargs):
            self.current_calls.append(kwargs)
            return {"candidate": {}, "submitted_event": {}}

        def return_from_rejection_in_session(self, _session, **kwargs):
            self.return_calls.append(kwargs)
            return {"transition_kind": "RETURN"}

    reviews = CandidateReviewSpy()
    _sessions, scoped, decisions, _auth, _wc = _build_runtime(
        stages=("TEAM_LEAD",), candidate_review_repository=reviews
    )
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(
        item,
        decided_by="accountant-lead",
        decision="REJECT",
        suffix="7",
    )

    first = decisions.ingest_wc_delivery(delivery)
    replay = decisions.ingest_wc_delivery(delivery)

    assert first["case_state"] == "REJECTED"
    assert replay["created"] is False
    assert len(reviews.current_calls) == 1
    assert len(reviews.return_calls) == 1
    assert reviews.return_calls[0]["reason"] == "decision 7"
    assert reviews.return_calls[0]["approval_case_id"] == CASE_ID


@pytest.mark.parametrize(
    ("principal", "expected"),
    (
        ("employee-requester", "requester"),
        ("candidate-preparer", "preparer"),
        ("business-approver", "business approver"),
        ("agent:finance", "cannot approve"),
    ),
)
def test_human_sod_and_agent_self_approval_are_denied(principal, expected) -> None:
    _sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with pytest.raises(EosAccountingApprovalError) as error:
        decisions.ingest_wc_delivery(_delivery(item, decided_by=principal))
    assert error.value.status_code == 403
    assert expected in error.value.detail.lower()


@pytest.mark.parametrize(
    ("overrides", "status"),
    (
        ({"active": False}, 403),
        ({"tenant_id": "other"}, 403),
        ({"subject_id": "other"}, 403),
        ({"scopes": []}, 403),
        ({"roles": ["EMPLOYEE"]}, 403),
        ({"company_ids": [str(uuid.uuid4())]}, 403),
        ({"revision_hash": "bad"}, 403),
    ),
)
def test_current_oa_authority_is_fail_closed(overrides, status) -> None:
    _sessions, scoped, decisions, auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.overrides = overrides
    with pytest.raises(EosAccountingApprovalError) as error:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))
    assert error.value.status_code == status

    auth.overrides = {}
    auth.denied = True
    with pytest.raises(EosAccountingApprovalError) as denied:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))
    assert denied.value.status_code == 403
    auth.denied = False
    auth.unavailable = True
    with pytest.raises(EosAccountingApprovalError) as unavailable:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


@pytest.mark.parametrize(
    "override",
    (
        {"scopes": "finance:journal:approve"},
        {"roles": [None]},
        {"company_ids": [""]},
    ),
)
def test_malformed_oa_collections_are_denied(override) -> None:
    _sessions, scoped, decisions, auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.overrides = override

    with pytest.raises(EosAccountingApprovalError) as denied:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))

    assert denied.value.status_code == 403


def test_non_mapping_oa_response_is_denied() -> None:
    _sessions, scoped, decisions, auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.effective_authorization = lambda **_kwargs: []

    with pytest.raises(EosAccountingApprovalError) as denied:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))

    assert denied.value.status_code == 403


def test_tenant_wide_finance_authority_without_company_projection_is_admitted() -> None:
    _sessions, scoped, decisions, auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    auth.overrides = {"company_ids": None}

    receipt = decisions.ingest_wc_delivery(
        _delivery(item, decided_by="accountant-lead")
    )

    assert receipt["observation_state"] == "ACCOUNTING_APPROVED_PENDING_POST"


def test_committed_stage_decision_replays_after_wc_publication_recovers() -> None:
    sessions, scoped, decisions, _auth, wc = _build_runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item, decided_by="accountant-lead")
    wc.fail = True

    with pytest.raises(EosAccountingApprovalError) as unavailable:
        decisions.ingest_wc_delivery(delivery)
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True

    wc.fail = False
    replay = decisions.ingest_wc_delivery(delivery)
    assert replay["created"] is False
    assert replay["case_state"] == "PENDING"
    assert replay["next_stage_publication"]["work_item"]["target_role_ref"] == "CEO"
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_SCOPED_APPROVAL_DECISION_TABLE)
            )
            == 1
        )


@pytest.mark.parametrize("mode", ("missing", "lineage"))
def test_committed_stage_decision_rejects_malformed_wc_recovery_response(mode) -> None:
    _sessions, scoped, decisions, _auth, wc = _build_runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    if mode == "missing":
        wc.response_override = lambda _expected: {}
    else:
        wc.response_override = lambda expected: {
            "work_item": {**expected, "semantic_hash": HASH_D}
        }

    with pytest.raises(EosAccountingApprovalError) as unavailable:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))

    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True


def test_duplicate_out_of_order_conflict_reject_and_missing_context() -> None:
    _sessions, scoped, decisions, _auth, _wc = _build_runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    first_delivery = _delivery(item, decided_by="accountant-lead", suffix="1")
    first = decisions.ingest_wc_delivery(first_delivery)

    changed = deepcopy(first_delivery)
    changed["decision"]["decision_comment"] = "changed"
    with pytest.raises(EosAccountingApprovalError) as changed_error:
        decisions.ingest_wc_delivery(changed)
    assert changed_error.value.status_code == 409

    out_of_order = _delivery(
        first["next_stage_publication"]["work_item"],
        decided_by="accountant-ceo",
        suffix="2",
    )
    out_of_order["work_item"]["resume_target_ref"] = (
        f"eos.scoped-approval-case:{CASE_ID}:stage:1"
    )
    with pytest.raises(EosAccountingApprovalError):
        decisions.ingest_wc_delivery(out_of_order)

    _sessions, scoped, decisions, _auth, _wc = _build_runtime()
    reject_receipt = _create_case(scoped)
    rejected = decisions.ingest_wc_delivery(
        _delivery(
            reject_receipt["wc_publication"]["work_item"],
            decided_by="accountant-lead",
            decision="REJECT",
            suffix="3",
        )
    )
    assert rejected["case_state"] == "REJECTED"
    assert rejected["accounting_approval_evidence"] is None

    sessions, scoped, decisions, _auth, wc = _build_runtime()
    missing_case = CASE_ID
    missing_operation = OPERATION_ID
    request_without_context = _request(
        case_id=missing_case,
        operation_id=missing_operation,
        review=None,
    )
    payload = dict(request_without_context.payload)
    payload["case"] = dict(payload["case"])
    payload["case"].pop("accounting_review")
    payload["payload_hash"] = scoped_approval_payload_hash(payload)
    receipt = scoped.request_case(payload, caller=_caller())
    missing_delivery = _delivery(
        receipt["wc_publication"]["work_item"],
        decided_by="accountant-lead",
        suffix="4",
    )
    missing_delivery["work_item"]["resume_target_ref"] = (
        f"eos.scoped-approval-case:{missing_case}:stage:1"
    )
    with pytest.raises(EosAccountingApprovalError) as missing:
        decisions.ingest_wc_delivery(missing_delivery)
    assert missing.value.status_code == 409
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE)
            )
            == 0
        )
    assert len(wc.items) == 1


@pytest.mark.parametrize("mode", ("unknown", "expired", "lineage", "version"))
def test_case_identity_expiry_and_terminal_lineage_are_fail_closed(mode) -> None:
    sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item, decided_by="accountant-lead")
    if mode == "unknown":
        unknown = str(uuid.uuid4())
        delivery["work_item"]["resume_target_ref"] = (
            f"eos.scoped-approval-case:{unknown}:stage:1"
        )
        expected_status = 404
    elif mode == "expired":
        with sessions.begin() as session:
            session.execute(
                update(EOS_SCOPED_APPROVAL_CASE_TABLE)
                .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
                .values(expires_at=NOW)
            )
        expected_status = 409
    elif mode == "lineage":
        delivery["work_item"]["semantic_hash"] = HASH_D
        expected_status = 409
    else:
        delivery["work_item"]["version"] += 1
        expected_status = 409

    with pytest.raises(EosAccountingApprovalError) as rejected:
        decisions.ingest_wc_delivery(delivery)

    assert rejected.value.status_code == expected_status


def test_non_accounting_case_and_missing_next_policy_stage_fail_closed() -> None:
    sessions, scoped, _decisions, _auth, _wc = _build_runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_APPROVAL_POLICY_TABLE)
            .where(EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == POLICY_ID)
            .values(transaction_type="DOCUMENT_SIGNOFF")
        )
    request = _request(case_id=str(uuid.uuid4()), operation_id=str(uuid.uuid4()))
    payload = dict(request.payload)
    payload["case"] = dict(payload["case"])
    payload["case"]["purpose"] = "DOCUMENT_SIGNOFF"
    payload["payload_hash"] = scoped_approval_payload_hash(payload)
    with pytest.raises(EosScopedApprovalError) as wrong_purpose:
        scoped.request_case(payload, caller=_caller())
    assert wrong_purpose.value.status_code == 422

    sessions, scoped, decisions, _auth, _wc = _build_runtime()
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            delete(EOS_APPROVAL_POLICY_STAGE_TABLE).where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == POLICY_ID,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == 2,
            )
        )
    with pytest.raises(EosAccountingApprovalError) as missing_stage:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))
    assert missing_stage.value.status_code == 409


def test_review_validation_binding_and_signoff_projection_fail_closed() -> None:
    _sessions, scoped, _decisions, _auth, _wc = _build_runtime()
    for mutation in (
        {"schema_version": "eos_accounting_review_context.v1"},
        {"candidate_id": "not-a-uuid"},
        {"candidate_revision": 2},
        {"candidate_revision": True},
        {"candidate_revision": "invalid"},
        {"candidate_hash": HASH_B},
        {"document_envelope_hash": "not-a-hash"},
        {"business_approver_subject_ids": []},
        {"business_approver_subject_ids": "business-approver"},
        {"business_approver_subject_ids": ["duplicate", "duplicate"]},
        {"candidate_preparer_subject_id": "not allowed"},
        {"original_currency": "usd"},
        {"functional_currency": "won"},
        {"original_amount": True},
        {"original_amount": "invalid"},
        {"market_base_rate": "0"},
        {"rate_reference_date": "bad"},
        {"rate_publication": ""},
        {"fx_exception": ""},
        {"unexpected": True},
    ):
        review = _review()
        review.update(mutation)
        request = _request(
            case_id=str(uuid.uuid4()),
            operation_id=str(uuid.uuid4()),
            review=review,
        )
        with pytest.raises(EosScopedApprovalError):
            scoped.request_case(request.payload, caller=_caller())

    with pytest.raises(AccountingSignoffViewError):
        accounting_signoff_view({})


def test_review_context_replay_is_idempotent_and_semantic_drift_conflicts() -> None:
    sessions, scoped, _decisions, _auth, _wc = _build_runtime()
    _create_case(scoped)
    repository = SqlAlchemyAccountingReviewContextRepository(
        sessions, clock=lambda: NOW
    )
    with sessions() as session:
        scoped_case = dict(
            session.execute(
                select(EOS_SCOPED_APPROVAL_CASE_TABLE).where(
                    EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID
                )
            )
            .mappings()
            .one()
        )
        replay = repository.create_in_session(
            session, scoped_case=scoped_case, review=_review()
        )
        assert replay["review_hash"] == accounting_review_hash(_review())
        changed = _review(fx_exception="Manual review")
        with pytest.raises(EosAccountingApprovalError) as conflict:
            repository.create_in_session(
                session, scoped_case=scoped_case, review=changed
            )
        assert conflict.value.status_code == 409


def test_signoff_projection_rejects_each_security_critical_field_class() -> None:
    _sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    evidence = decisions.ingest_wc_delivery(
        _delivery(item, decided_by="accountant-lead")
    )["accounting_approval_evidence"]
    mutations = (
        {"observation_state": "POSTED"},
        {"candidate_revision": 0},
        {"proof_hash": "bad"},
        {"approver_subject_id": ""},
        {"decided_at": ""},
        {"evidence_id": "bad"},
    )
    for mutation in mutations:
        changed = {**evidence, **mutation}
        with pytest.raises(AccountingSignoffViewError):
            accounting_signoff_view(changed)


def test_decision_rejects_document_signoff_substitution_and_naive_clock() -> None:
    sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    with sessions.begin() as session:
        session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
            .values(purpose="DOCUMENT_SIGNOFF")
        )
    with pytest.raises(EosAccountingApprovalError) as wrong_purpose:
        decisions.ingest_wc_delivery(_delivery(item, decided_by="accountant-lead"))
    assert wrong_purpose.value.status_code == 409

    sessions, scoped, _decisions, auth, wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    naive_clock_service = EosAccountingApprovalService(
        session_factory=sessions,
        authorization_source=auth,
        wc_client=wc,
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(EosAccountingApprovalError) as naive_clock:
        naive_clock_service.ingest_wc_delivery(
            _delivery(item, decided_by="accountant-lead")
        )
    assert naive_clock.value.status_code == 422


@pytest.mark.parametrize("mode", ("case", "review"))
def test_replay_fails_closed_when_persisted_lineage_is_missing(mode) -> None:
    sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item, decided_by="accountant-lead")
    decisions.ingest_wc_delivery(delivery)
    table = (
        EOS_SCOPED_APPROVAL_CASE_TABLE
        if mode == "case"
        else EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE
    )
    with sessions.begin() as session:
        session.execute(delete(table).where(table.c.case_id == CASE_ID))

    with pytest.raises(EosAccountingApprovalError) as corrupted:
        decisions.ingest_wc_delivery(delivery)

    assert corrupted.value.status_code in {404, 409}


def test_multiple_replay_identity_matches_and_stage_collision_fail_closed() -> None:
    sessions, scoped, decisions, _auth, _wc = _build_runtime()
    first_item = _create_case(scoped)["wc_publication"]["work_item"]
    first_delivery = _delivery(first_item, decided_by="accountant-lead", suffix="1")
    first = decisions.ingest_wc_delivery(first_delivery)
    next_item = first["next_stage_publication"]["work_item"]
    with sessions.begin() as session:
        first_record = dict(
            session.execute(
                select(EOS_SCOPED_APPROVAL_DECISION_TABLE).where(
                    EOS_SCOPED_APPROVAL_DECISION_TABLE.c.case_id == CASE_ID
                )
            )
            .mappings()
            .one()
        )
        second_record = {
            **first_record,
            "stage_order": 2,
            "wc_work_item_id": str(uuid.uuid4()),
            "wc_decision_id": str(uuid.uuid4()),
            "wc_event_id": str(uuid.uuid4()),
            "wc_outbox_id": str(uuid.uuid4()),
            "decision_hash": HASH_D,
        }
        session.execute(
            EOS_SCOPED_APPROVAL_DECISION_TABLE.insert().values(**second_record)
        )
    mixed = _delivery(next_item, decided_by="accountant-ceo", suffix="2")
    mixed["decision"]["decision_id"] = first_record["wc_decision_id"]
    mixed["event"]["decision_id"] = first_record["wc_decision_id"]
    mixed["event"]["event_id"] = second_record["wc_event_id"]
    with pytest.raises(EosAccountingApprovalError) as collision:
        decisions.ingest_wc_delivery(mixed)
    assert collision.value.status_code == 409

    sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    decisions.ingest_wc_delivery(
        _delivery(item, decided_by="accountant-lead", suffix="1")
    )
    with sessions.begin() as session:
        session.execute(
            update(EOS_SCOPED_APPROVAL_CASE_TABLE)
            .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.case_id == CASE_ID)
            .values(
                state="PENDING",
                active_stage_order=1,
                target_role_ref="TEAM_LEAD",
                version=1,
                decided_at=None,
            )
        )
        session.execute(
            update(EOS_SCOPED_APPROVAL_DECISION_TABLE)
            .where(EOS_SCOPED_APPROVAL_DECISION_TABLE.c.case_id == CASE_ID)
            .values(wc_work_item_id=str(uuid.uuid4()))
        )
    with pytest.raises(EosAccountingApprovalError) as duplicate_stage:
        decisions.ingest_wc_delivery(
            _delivery(item, decided_by="accountant-lead", suffix="2")
        )
    assert duplicate_stage.value.status_code == 409


@pytest.mark.parametrize("semantic_drift", (False, True))
def test_concurrent_decision_between_replay_preflight_and_lock_is_fail_closed(
    monkeypatch, semantic_drift
) -> None:
    _sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item, decided_by="accountant-lead")
    original = accounting_approval_module._load_decision_by_identity
    calls = 0

    def interleaved(session, admitted):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        if calls == 2:
            return {
                "decision_hash": (
                    HASH_D if semantic_drift else admitted["decision_hash"]
                )
            }
        return original(session, admitted)

    monkeypatch.setattr(
        accounting_approval_module, "_load_decision_by_identity", interleaved
    )
    if semantic_drift:
        with pytest.raises(EosAccountingApprovalError) as conflict:
            decisions.ingest_wc_delivery(delivery)
        assert conflict.value.status_code == 409
    else:
        receipt = decisions.ingest_wc_delivery(delivery)
        assert receipt["created"] is False
        assert receipt["case_state"] == "PENDING"


def test_persisted_timestamp_adapter_rejects_corruption_and_normalizes_timezone() -> (
    None
):
    with pytest.raises(EosAccountingApprovalError) as malformed:
        accounting_approval_module._persisted_datetime("not-a-timestamp")
    assert malformed.value.status_code == 422

    seoul = timezone(timedelta(hours=9))
    value = datetime(2026, 11, 11, 14, 0, tzinfo=seoul)
    assert accounting_approval_module._persisted_datetime(value) == NOW


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("schema_version",), "wc_approval_delivery.v0"),
        (("event",), None),
        (("work_item", "resume_target_ref"), "ae-wait:not-accounting"),
        (("event", "event_type"), "APPROVAL_DECIDED"),
        (("event", "approval_domain"), "NSL_WRITE"),
        (("event", "decision"), "REJECT"),
        (("work_item", "state"), "PENDING"),
        (("decision", "schema_version"), "wc_approval_decision.v0"),
        (("event", "schema_version"), "wc_approval_event.v0"),
        (("decision", "authorized_by_oa"), False),
        (("decision", "decision_version"), 2),
        (("event", "decided_by"), "other-approver"),
        (("event", "occurred_at"), "2026-11-11T00:00:00Z"),
        (("decision", "decided_at"), None),
        (("decision", "authorization_checked_at"), "invalid"),
        (("decision", "decision_version"), True),
        (("decision", "oa_decision_ref"), "not allowed"),
        (("decision", "authorization_revision_hash"), "bad"),
    ),
)
def test_wc_delivery_lineage_and_terminal_contract_fail_closed(path, value) -> None:
    _sessions, scoped, decisions, _auth, _wc = _build_runtime(stages=("TEAM_LEAD",))
    item = _create_case(scoped)["wc_publication"]["work_item"]
    delivery = _delivery(item, decided_by="accountant-lead")
    target = delivery
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(EosAccountingApprovalError) as invalid:
        decisions.ingest_wc_delivery(delivery)

    assert invalid.value.status_code == 422


class FakeAccountingApprovalService:
    def ingest_wc_delivery(self, payload):
        if payload.get("fail"):
            raise EosAccountingApprovalError("DENIED", "denied", status_code=403)
        return {"schema_version": "receipt", "case_state": "APPROVED"}


def test_eos_route_dispatches_scoped_delivery_and_preserves_legacy_boundary() -> None:
    from nex_eos.accounting_approval_api import is_scoped_approval_delivery

    assert is_scoped_approval_delivery({}) is False
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s2-03",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_accounting_approval_service = FakeAccountingApprovalService()
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    payload = {
        "work_item": {
            "resume_target_ref": f"eos.scoped-approval-case:{CASE_ID}:stage:1"
        }
    }
    response = client.post(
        "/internal/v1/approval-decision-events",
        json=payload,
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["case_state"] == "APPROVED"
    denied_payload = {**payload, "fail": True}
    denied = client.post(
        "/internal/v1/approval-decision-events",
        json=denied_payload,
        headers={"Authorization": f"Bearer {token.access_token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "DENIED"
    app.state.eos_accounting_approval_service = None
    assert (
        client.post(
            "/internal/v1/approval-decision-events",
            json=payload,
            headers={"Authorization": f"Bearer {token.access_token}"},
        ).status_code
        == 503
    )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S2-03 EOS PostgreSQL smoke is disabled",
)
def test_actual_postgres_human_approval_evidence_and_immutability() -> None:
    schema_name = f"mybee_s203_{uuid.uuid4().hex}"
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
    run_service_migrations("nex-eos", database_url=scoped_url, profile="test")
    engine = create_engine(scoped_url, pool_pre_ping=True)
    try:
        sessions, scoped, decisions, _auth, _wc = _build_runtime(
            engine=engine, stages=("TEAM_LEAD",)
        )
        item = _create_case(scoped)["wc_publication"]["work_item"]
        receipt = decisions.ingest_wc_delivery(
            _delivery(item, decided_by="accountant-lead")
        )
        assert receipt["observation_state"] == "ACCOUNTING_APPROVED_PENDING_POST"
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(
                        EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE
                    )
                )
                == 1
            )
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            row = connection.execute(
                sql.SQL(
                    "SELECT state, version FROM {}.eos_scoped_approval_case"
                ).format(sql.Identifier(schema_name))
            ).fetchone()
            assert row == ("APPROVED", 2)
            with pytest.raises(psycopg.Error):
                connection.execute(
                    sql.SQL(
                        "UPDATE {}.eos_accounting_approval_evidence "
                        "SET approver_subject_id = 'tampered'"
                    ).format(sql.Identifier(schema_name))
                )
    finally:
        engine.dispose()
        with psycopg.connect(psycopg_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
            )
