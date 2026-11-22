from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE,
    EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE,
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_CANDIDATE_REVIEW_EVENT_TABLE,
    EOS_METADATA,
    EOS_SCOPED_APPROVAL_CASE_TABLE,
    EOS_SCOPED_APPROVAL_DECISION_TABLE,
    EOS_VOUCHER_CANDIDATE_REVISION_TABLE,
    EOS_VOUCHER_CANDIDATE_TABLE,
    EosAccountingPostingAdmissionError,
    EosAccountingPostingAdmissionService,
    finance_v2_api,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_eos.project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationEvidence,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)
TENANT = "VO00"
COMPANY_ID = "44000000-0000-4000-8000-000000000001"
PROJECT_ID = "44000000-0000-4000-8000-000000000002"
PROJECT_CODE = "VO00D260001"
CANDIDATE_ID = "44000000-0000-4000-8000-000000000003"
REVISION_ID = "44000000-0000-4000-8000-000000000004"
CASE_ID = "44000000-0000-4000-8000-000000000005"
POLICY_ID = "44000000-0000-4000-8000-000000000006"
OPERATION_ID = "44000000-0000-4000-8000-000000000007"
ENVELOPE_ID = "44000000-0000-4000-8000-000000000008"
EVIDENCE_ID = "44000000-0000-4000-8000-000000000009"
DECISION_ID = "44000000-0000-4000-8000-000000000010"
EVENT_ID = "44000000-0000-4000-8000-000000000011"
PERIOD_ID = "44000000-0000-4000-8000-000000000012"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64


class AuthorizationSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.overrides: dict[str, object] = {}
        self.error: Exception | None = None
        self.on_call = None

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls.append((tenant_id, subject_id))
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        value = {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "roles": ["CEO"],
            "scopes": ["finance:journal:approve"],
            "company_ids": [COMPANY_ID],
            "revision_hash": "1" * 64,
            "decision_ref": "oa-authz:posting-approver",
        }
        value.update(self.overrides)
        return value


class ProjectAuthorizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: EosProjectAuthorizationError | None = None
        self.project_status = "ACTIVE"

    def authorize(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return EosProjectAuthorizationEvidence(
            decision_ref=HASH_D,
            project_code=PROJECT_CODE,
            project_role="ACCOUNTANT",
            project_status=self.project_status,
            source_version=3,
            projection_event_hash=HASH_E,
            authorization_revision_hash=HASH_F,
            decided_at=NOW.isoformat(),
        )


def _runtime(*, now=NOW):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    _seed(sessions)
    authorization = AuthorizationSource()
    project_authorizer = ProjectAuthorizer()
    service = EosAccountingPostingAdmissionService(
        session_factory=sessions,
        authorization_source=authorization,
        project_authorizer=project_authorizer,
        admission_ttl_seconds=30,
        clock=lambda: now,
    )
    return sessions, service, authorization, project_authorizer


def _seed(sessions) -> None:
    with sessions.begin() as session:
        session.execute(
            EOS_APPROVAL_POLICY_STAGE_TABLE.insert().values(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                stage_order=1,
                position_type="CEO",
                quorum_count=1,
                separation_policy="REQUESTER_EXCLUDED",
            )
        )
        session.execute(
            EOS_VOUCHER_CANDIDATE_TABLE.insert().values(
                tenant_id=TENANT,
                candidate_id=CANDIDATE_ID,
                company_id=COMPANY_ID,
                project_id=PROJECT_ID,
                project_code=PROJECT_CODE,
                document_envelope_id=ENVELOPE_ID,
                preparer_subject_id="candidate-preparer",
                source_kind="EXPENSE_CLAIM",
                source_record_ref="expense:4401",
                business_work_code="FL1000001",
                transaction_currency="KRW",
                recognition_date=NOW.date(),
                state="READY_FOR_REVIEW",
                current_revision_no=1,
                version=2,
                created_business_operation_id=OPERATION_ID,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_VOUCHER_CANDIDATE_REVISION_TABLE.insert().values(
                tenant_id=TENANT,
                candidate_id=CANDIDATE_ID,
                revision_no=1,
                revision_id=REVISION_ID,
                candidate_hash=HASH_A,
                source_evidence_hash=HASH_B,
                approved_document_hash=HASH_B,
                attachment_manifest_hash=HASH_C,
                fx_rate_set_hash=HASH_C,
                posting_rule_release_hash=HASH_D,
                account_policy_release_hash=HASH_E,
                journal_payload_hash=HASH_F,
                created_by="candidate-preparer",
                created_at=NOW,
            )
        )
        session.execute(
            EOS_SCOPED_APPROVAL_CASE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                idempotency_key="w40-s4-01",
                company_id=COMPANY_ID,
                purpose="ACCOUNTING_POSTING",
                scope_type="PROJECT",
                project_set_hash=HASH_B,
                subject_ref=f"eos.voucher-candidate:{CANDIDATE_ID}",
                subject_revision=1,
                subject_hash=HASH_A,
                requester_ref_type="oa.user",
                requester_id="employee-requester",
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=HASH_C,
                oa_decision_ref="oa-authz:requester",
                authorization_revision_hash=HASH_D,
                authorization_checked_at=NOW,
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                target_role_ref=None,
                version=2,
                case_hash=HASH_E,
                created_business_operation_id=OPERATION_ID,
                correlation_id="correlation-w40-s4-01",
                causation_id="causation-w40-s4-01",
                expires_at=NOW + timedelta(days=1),
                created_at=NOW,
                updated_at=NOW,
                decided_at=NOW,
            )
        )
        session.execute(
            EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                review_schema_version="eos_accounting_review_context.v3",
                candidate_id=CANDIDATE_ID,
                candidate_revision=1,
                candidate_hash=HASH_A,
                candidate_version=1,
                validation_hash=HASH_F,
                validation_observed_at=NOW,
                document_envelope_hash=HASH_B,
                fx_rate_set_hash=HASH_C,
                rule_release_hash=HASH_D,
                accounting_period_id=PERIOD_ID,
                candidate_preparer_id="candidate-preparer",
                business_approver_ids=["business-approver"],
                original_currency="KRW",
                original_amount="10000",
                market_base_rate="1",
                rate_reference_date=NOW.date(),
                rate_publication="SAME_CURRENCY",
                functional_currency="KRW",
                functional_amount="10000",
                fx_exception=None,
                review_hash=HASH_E,
                created_at=NOW,
            )
        )
        session.execute(
            EOS_CANDIDATE_REVIEW_EVENT_TABLE.insert().values(
                tenant_id=TENANT,
                event_id=EVENT_ID,
                candidate_id=CANDIDATE_ID,
                candidate_revision=1,
                candidate_hash=HASH_A,
                approval_case_id=CASE_ID,
                transition_kind="SUBMIT",
                from_state="DRAFT",
                to_state="READY_FOR_REVIEW",
                expected_version=1,
                resulting_version=2,
                actor_subject_id="employee-requester",
                reason=None,
                validation_hash=HASH_F,
                review_hash=HASH_E,
                event_hash=HASH_B,
                created_at=NOW,
            )
        )
        session.execute(
            EOS_SCOPED_APPROVAL_DECISION_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                stage_order=1,
                wc_work_item_id=str(uuid.uuid4()),
                wc_decision_id=DECISION_ID,
                wc_event_id=str(uuid.uuid4()),
                wc_outbox_id=str(uuid.uuid4()),
                decision="APPROVE",
                decision_version=1,
                decided_by="accountant-cfo",
                decision_comment="Approved",
                wc_oa_decision_ref="wc-oa:accountant-cfo",
                wc_authorization_revision_hash=HASH_B,
                oa_decision_ref="oa-authz:accountant-cfo",
                authorization_revision_hash=HASH_C,
                authorization_checked_at=NOW,
                decided_at=NOW,
                decision_hash=HASH_D,
                recorded_at=NOW,
            )
        )
        session.execute(
            EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                evidence_id=EVIDENCE_ID,
                company_id=COMPANY_ID,
                candidate_id=CANDIDATE_ID,
                candidate_revision=1,
                candidate_hash=HASH_A,
                document_envelope_hash=HASH_B,
                fx_rate_set_hash=HASH_C,
                rule_release_hash=HASH_D,
                accounting_period_id=PERIOD_ID,
                approver_subject_id="accountant-cfo",
                approval_policy_hash=HASH_C,
                wc_final_decision_id=DECISION_ID,
                oa_authorization_revision_hash=HASH_C,
                decided_at=NOW,
                proof_hash=HASH_F,
                created_at=NOW,
            )
        )


def _request(**overrides):
    value = {
        "schema_version": "eos_accounting_posting_admission_request.v1",
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "expected_candidate_version": 2,
        "expected_candidate_revision": 1,
        "expected_candidate_hash": HASH_A,
        "accounting_approval_evidence_id": EVIDENCE_ID,
        "correlation_id": "correlation-w40-s4-01-admission",
    }
    value.update(overrides)
    return value


def test_exact_proof_and_fresh_oa_issue_bounded_posting_admission() -> None:
    sessions, service, authorization, project_authorizer = _runtime()

    receipt = service.admit(CANDIDATE_ID, _request())

    assert receipt["operation_id"] == "FINANCE.VOUCHER.APPROVE_AND_POST.ADMISSION"
    assert receipt["candidate_version"] == 2
    assert receipt["candidate_revision"] == 1
    assert receipt["accounting_proof_hash"] == HASH_F
    assert receipt["fresh_oa_revision_hash"] == "sha256:" + "1" * 64
    assert receipt["fresh_project_authorization"]["project_code"] == PROJECT_CODE
    assert receipt["admission_hash"].startswith("sha256:")
    assert authorization.calls == [(TENANT, "accountant-cfo")]
    assert project_authorizer.calls[0]["action"] == "finance:journal:approve"
    with sessions.begin() as session:
        assert service.require_current_in_session(session, receipt) == receipt


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"active": False}, "EOS_ACCOUNTING_OA_SCOPE_DENIED"),
        ({"roles": ["GROUP_LEAD"]}, "EOS_ACCOUNTING_OA_SCOPE_DENIED"),
        ({"scopes": []}, "EOS_ACCOUNTING_OA_SCOPE_DENIED"),
        ({"company_ids": [str(uuid.uuid4())]}, "EOS_ACCOUNTING_OA_SCOPE_DENIED"),
        ({"revision_hash": "bad"}, "EOS_ACCOUNTING_OA_SCOPE_DENIED"),
    ],
)
def test_current_oa_authority_is_revalidated_fail_closed(overrides, error_code) -> None:
    _sessions, service, authorization, _project_authorizer = _runtime()
    authorization.overrides = overrides
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.error_code == error_code
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "error",
    [AuthorizationSubjectDenied("revoked"), RuntimeError("OA offline")],
)
def test_oa_denial_and_unavailability_remain_distinct(error) -> None:
    _sessions, service, authorization, _project_authorizer = _runtime()
    authorization.error = error
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.status_code == (
        403 if isinstance(error, AuthorizationSubjectDenied) else 503
    )


def test_project_authority_is_current_and_project_scoped() -> None:
    _sessions, service, _authorization, project_authorizer = _runtime()
    project_authorizer.error = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_DENIED",
        "denied",
        status_code=403,
    )
    with pytest.raises(EosAccountingPostingAdmissionError) as denied:
        service.admit(CANDIDATE_ID, _request())
    assert denied.value.error_code == "EOS_ACCOUNTING_OA_SCOPE_DENIED"

    _sessions, service, _authorization, project_authorizer = _runtime()
    project_authorizer.project_status = "CLOSED"
    with pytest.raises(EosAccountingPostingAdmissionError) as closed:
        service.admit(CANDIDATE_ID, _request())
    assert closed.value.status_code == 403

    _sessions, service, _authorization, project_authorizer = _runtime()
    project_authorizer.error = EosProjectAuthorizationError(
        "EOS_PROJECT_AUTHORIZATION_UNAVAILABLE",
        "offline",
        status_code=503,
        retryable=True,
    )
    with pytest.raises(EosAccountingPostingAdmissionError) as unavailable:
        service.admit(CANDIDATE_ID, _request())
    assert unavailable.value.status_code == 503


@pytest.mark.parametrize(
    ("table", "values", "expected"),
    [
        (
            EOS_SCOPED_APPROVAL_CASE_TABLE,
            {"purpose": "DOCUMENT_SIGNOFF"},
            "EOS_ACCOUNTING_PROOF_PURPOSE_MISMATCH",
        ),
        (
            EOS_VOUCHER_CANDIDATE_TABLE,
            {"state": "RETURNED_FOR_CORRECTION"},
            "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE",
        ),
        (
            EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE,
            {"approver_subject_id": "candidate-preparer"},
            "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE",
        ),
    ],
)
def test_purpose_candidate_and_sod_lineage_fail_closed(table, values, expected) -> None:
    sessions, service, _authorization, _project_authorizer = _runtime()
    key = (
        table.c.case_id == CASE_ID
        if "case_id" in table.c
        else table.c.candidate_id == CANDIDATE_ID
    )
    with sessions.begin() as session:
        session.execute(
            update(table).where(table.c.tenant_id == TENANT, key).values(**values)
        )
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.error_code == expected


def test_receipt_expiry_tamper_and_local_drift_are_rejected() -> None:
    sessions, service, _authorization, _project_authorizer = _runtime()
    receipt = service.admit(CANDIDATE_ID, _request())
    tampered = deepcopy(receipt)
    tampered["candidate_hash"] = HASH_B
    with (
        sessions.begin() as session,
        pytest.raises(EosAccountingPostingAdmissionError) as invalid,
    ):
        service.require_current_in_session(session, tampered)
    assert invalid.value.error_code == "EOS_ACCOUNTING_POSTING_ADMISSION_INVALID"

    with sessions.begin() as session:
        session.execute(
            update(EOS_VOUCHER_CANDIDATE_TABLE)
            .where(
                EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == TENANT,
                EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == CANDIDATE_ID,
            )
            .values(state="RETURNED_FOR_CORRECTION")
        )
    with (
        sessions.begin() as session,
        pytest.raises(EosAccountingPostingAdmissionError) as drift,
    ):
        service.require_current_in_session(session, receipt)
    assert drift.value.error_code == "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"

    _sessions, expired_service, _authorization, _project_authorizer = _runtime(
        now=NOW + timedelta(minutes=1)
    )
    with (
        _sessions.begin() as session,
        pytest.raises(EosAccountingPostingAdmissionError) as expired,
    ):
        expired_service.require_current_in_session(session, receipt)
    assert expired.value.error_code == "EOS_ACCOUNTING_OA_AUTHORIZATION_STALE"


def test_snapshot_drift_during_external_authorization_is_rejected() -> None:
    sessions, service, authorization, _project_authorizer = _runtime()

    def mutate_candidate():
        with sessions.begin() as session:
            session.execute(
                update(EOS_VOUCHER_CANDIDATE_TABLE)
                .where(
                    EOS_VOUCHER_CANDIDATE_TABLE.c.tenant_id == TENANT,
                    EOS_VOUCHER_CANDIDATE_TABLE.c.candidate_id == CANDIDATE_ID,
                )
                .values(state="RETURNED_FOR_CORRECTION")
            )

    authorization.on_call = mutate_candidate
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.error_code == "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"


def test_snapshot_hash_drift_during_external_authorization_is_rejected() -> None:
    sessions, service, authorization, _project_authorizer = _runtime()

    def mutate_proof():
        with sessions.begin() as session:
            session.execute(
                update(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE)
                .where(
                    EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == TENANT,
                    EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.case_id == CASE_ID,
                )
                .values(proof_hash=HASH_A)
            )

    authorization.on_call = mutate_proof
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.error_code == "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("case_not_final", "EOS_ACCOUNTING_APPROVAL_REQUIRED"),
        ("legacy_review", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
        ("requested_version", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
        ("subject_hash", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
        ("validation_hash", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
        ("evidence_fx", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
        ("human_principal", "EOS_ACCOUNTING_SOD_DENIED"),
        ("requester_self", "EOS_ACCOUNTING_SOD_DENIED"),
        ("sole_business_approver", "EOS_ACCOUNTING_SOD_DENIED"),
        ("malformed_business_approvers", "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"),
    ],
)
def test_exact_proof_lineage_matrix_is_fail_closed(mutation, expected) -> None:
    sessions, service, _authorization, _project_authorizer = _runtime()
    request = _request()
    with sessions.begin() as session:
        if mutation == "case_not_final":
            session.execute(
                update(EOS_SCOPED_APPROVAL_CASE_TABLE)
                .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == TENANT)
                .values(state="REJECTED")
            )
        elif mutation == "legacy_review":
            session.execute(
                update(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE)
                .where(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == TENANT)
                .values(review_schema_version="eos_accounting_review_context.v2")
            )
        elif mutation == "requested_version":
            request["expected_candidate_version"] = 1
        elif mutation == "subject_hash":
            session.execute(
                update(EOS_SCOPED_APPROVAL_CASE_TABLE)
                .where(EOS_SCOPED_APPROVAL_CASE_TABLE.c.tenant_id == TENANT)
                .values(subject_hash=HASH_B)
            )
        elif mutation == "validation_hash":
            session.execute(
                update(EOS_CANDIDATE_REVIEW_EVENT_TABLE)
                .where(EOS_CANDIDATE_REVIEW_EVENT_TABLE.c.tenant_id == TENANT)
                .values(validation_hash=HASH_A)
            )
        elif mutation == "evidence_fx":
            session.execute(
                update(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE)
                .where(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == TENANT)
                .values(fx_rate_set_hash=HASH_A)
            )
        elif mutation in {"human_principal", "requester_self"}:
            principal = (
                "service:accounting"
                if mutation == "human_principal"
                else "employee-requester"
            )
            session.execute(
                update(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE)
                .where(EOS_ACCOUNTING_APPROVAL_EVIDENCE_TABLE.c.tenant_id == TENANT)
                .values(approver_subject_id=principal)
            )
            session.execute(
                update(EOS_SCOPED_APPROVAL_DECISION_TABLE)
                .where(EOS_SCOPED_APPROVAL_DECISION_TABLE.c.tenant_id == TENANT)
                .values(decided_by=principal)
            )
        elif mutation == "sole_business_approver":
            session.execute(
                update(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE)
                .where(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == TENANT)
                .values(business_approver_ids=["accountant-cfo"])
            )
        elif mutation == "malformed_business_approvers":
            session.execute(
                update(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE)
                .where(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == TENANT)
                .values(business_approver_ids=[""])
            )
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, request)
    assert exc.value.error_code == expected


@pytest.mark.parametrize("missing", ["evidence", "review", "final_role"])
def test_missing_proof_lineage_is_rejected(missing) -> None:
    sessions, service, _authorization, _project_authorizer = _runtime()
    request = _request()
    with sessions.begin() as session:
        if missing == "evidence":
            request["accounting_approval_evidence_id"] = str(uuid.uuid4())
        elif missing == "review":
            session.execute(
                delete(EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE).where(
                    EOS_ACCOUNTING_REVIEW_CONTEXT_TABLE.c.tenant_id == TENANT
                )
            )
        else:
            session.execute(
                delete(EOS_APPROVAL_POLICY_STAGE_TABLE).where(
                    EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == TENANT
                )
            )
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, request)
    assert exc.value.error_code == "EOS_ACCOUNTING_APPROVAL_REQUIRED"


@pytest.mark.parametrize(
    "override",
    [
        {"roles": "CEO"},
        {"scopes": [""]},
        {"company_ids": "all"},
        {"decision_ref": "bad ref"},
    ],
)
def test_malformed_oa_collections_and_reference_are_denied(override) -> None:
    _sessions, service, authorization, _project_authorizer = _runtime()
    authorization.overrides = override
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, _request())
    assert exc.value.status_code in {403, 422}


def test_non_mapping_oa_and_persistence_failure_are_typed() -> None:
    sessions, service, authorization, _project_authorizer = _runtime()
    authorization.effective_authorization = lambda **_kwargs: []
    with pytest.raises(EosAccountingPostingAdmissionError) as malformed:
        service.admit(CANDIDATE_ID, _request())
    assert malformed.value.status_code == 403

    sessions.kw["bind"].dispose()
    with pytest.raises(EosAccountingPostingAdmissionError) as unavailable:
        service.admit(CANDIDATE_ID, _request())
    assert unavailable.value.status_code == 503


def test_local_receipt_semantics_and_clock_are_fail_closed() -> None:
    sessions, service, _authorization, _project_authorizer = _runtime()
    receipt = service.admit(CANDIDATE_ID, _request())

    invalid_schema = {**receipt, "schema_version": "v0"}
    with sessions.begin() as session, pytest.raises(EosAccountingPostingAdmissionError):
        service.require_current_in_session(session, invalid_schema)

    stale_snapshot = {**receipt, "snapshot_hash": HASH_A}
    semantics = {
        key: value for key, value in stale_snapshot.items() if key != "admission_hash"
    }
    stale_snapshot["admission_hash"] = semantic_sha256_hash_ref(semantics)
    with (
        sessions.begin() as session,
        pytest.raises(EosAccountingPostingAdmissionError) as stale,
    ):
        service.require_current_in_session(session, stale_snapshot)
    assert stale.value.error_code == "EOS_ACCOUNTING_CANDIDATE_REVISION_STALE"

    bad_expiry = {**receipt, "expires_at": "not-a-date"}
    semantics = {
        key: value for key, value in bad_expiry.items() if key != "admission_hash"
    }
    bad_expiry["admission_hash"] = semantic_sha256_hash_ref(semantics)
    with sessions.begin() as session, pytest.raises(EosAccountingPostingAdmissionError):
        service.require_current_in_session(session, bad_expiry)

    naive_service = EosAccountingPostingAdmissionService(
        session_factory=sessions,
        authorization_source=AuthorizationSource(),
        project_authorizer=ProjectAuthorizer(),
        clock=lambda: NOW.replace(tzinfo=None),
    )
    with pytest.raises(EosAccountingPostingAdmissionError):
        naive_service.admit(CANDIDATE_ID, _request())


@pytest.mark.parametrize(
    "value",
    [
        {},
        {**_request(), "extra": True},
        {**_request(), "schema_version": "v0"},
        {**_request(), "expected_candidate_version": 0},
        {**_request(), "expected_candidate_hash": "bad"},
        {**_request(), "accounting_approval_evidence_id": "bad"},
    ],
)
def test_request_contract_is_strict(value) -> None:
    _sessions, service, _authorization, _project_authorizer = _runtime()
    with pytest.raises(EosAccountingPostingAdmissionError) as exc:
        service.admit(CANDIDATE_ID, value)
    assert exc.value.status_code == 422


def test_ttl_configuration_is_bounded() -> None:
    sessions, _service, authorization, project_authorizer = _runtime()
    with pytest.raises(ValueError):
        EosAccountingPostingAdmissionService(
            session_factory=sessions,
            authorization_source=authorization,
            project_authorizer=project_authorizer,
            admission_ttl_seconds=0,
        )


def test_installed_api_exposes_admission_and_fails_closed_when_unwired(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        finance_v2_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api",
            audience="nex-eos",
            scopes=("service:call",),
        ),
    )
    _sessions, service, _authorization, _project_authorizer = _runtime()
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_accounting_posting_admission_service = service
    with TestClient(app) as client:
        admitted = client.post(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/posting-admission",
            json=_request(),
            headers={"Authorization": "Bearer service-token"},
        )
    assert admitted.status_code == 200
    assert admitted.json()["candidate_id"] == CANDIDATE_ID

    del app.state.eos_accounting_posting_admission_service
    with TestClient(app) as client:
        unavailable = client.post(
            f"/internal/v2/finance/voucher-candidates/{CANDIDATE_ID}/posting-admission",
            json=_request(),
            headers={"Authorization": "Bearer service-token"},
        )
    assert unavailable.status_code == 503
