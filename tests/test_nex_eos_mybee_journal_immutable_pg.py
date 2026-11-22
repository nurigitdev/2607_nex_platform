from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE,
    EOS_METADATA,
    EosJournalError,
    EosJournalQueryService,
    SqlAlchemyEosJournalRepository,
    admit_posted_journal,
    build_acceptance_hash,
    build_journal_hash,
    build_line_hash,
    finance_v2_api,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.finance_v2_api import register_finance_v2_routes
from nex_eos.project_authorization import (
    EosProjectAuthorizationError,
    EosProjectAuthorizationEvidence,
)
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)
TENANT = "VO00"
COMPANY_ID = "45000000-0000-4000-8000-000000000001"
JOURNAL_ID = "45000000-0000-4000-8000-000000000002"
CANDIDATE_ID = "45000000-0000-4000-8000-000000000003"
PERIOD_ID = "45000000-0000-4000-8000-000000000004"
ACCEPTANCE_ID = "45000000-0000-4000-8000-000000000005"
EVIDENCE_ID = "45000000-0000-4000-8000-000000000006"
CASE_ID = "45000000-0000-4000-8000-000000000007"
DECISION_ID = "45000000-0000-4000-8000-000000000008"
DOCUMENT_ID = "45000000-0000-4000-8000-000000000009"
OPERATION_ID = "45000000-0000-4000-8000-000000000010"
ACCOUNT_ID = "45000000-0000-4000-8000-000000000011"
POLICY_ID = "45000000-0000-4000-8000-000000000012"
PROJECT_ID = "45000000-0000-4000-8000-000000000013"
PROJECT_CODE = "VO00D260001"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64
HASH_E = "sha256:" + "e" * 64
HASH_F = "sha256:" + "f" * 64


class AuthorizationSource:
    def __init__(self) -> None:
        self.active = True
        self.scopes: object = ["finance:report:read"]
        self.company_ids: object = [COMPANY_ID]
        self.revision: object = "1" * 64
        self.error: Exception | None = None

    def effective_authorization(self, *, tenant_id, subject_id):
        if self.error is not None:
            raise self.error
        return {
            "active": self.active,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": self.scopes,
            "company_ids": self.company_ids,
            "revision_hash": self.revision,
        }


class ProjectAuthorizer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: EosProjectAuthorizationError | None = None

    def authorize(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return EosProjectAuthorizationEvidence(
            decision_ref=HASH_A,
            project_code=PROJECT_CODE,
            project_role="MEMBER",
            project_status="ACTIVE",
            source_version=3,
            projection_event_hash=HASH_B,
            authorization_revision_hash=HASH_C,
            decided_at=NOW.isoformat(),
        )


class StaticRepository:
    def __init__(self, value) -> None:
        self.value = value

    def get(self, **_kwargs):
        return deepcopy(self.value)


def _line(line_no: int, *, debit: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "journal_id": JOURNAL_ID,
        "line_no": line_no,
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_source_line_no": line_no,
        "account_id": ACCOUNT_ID,
        "account_code_snapshot": "110100",
        "account_name_snapshot": "현금",
        "account_policy_id": POLICY_ID,
        "account_policy_release_hash": HASH_A,
        "posting_rule_release_hash": HASH_B,
        "project_id": PROJECT_ID,
        "project_code": PROJECT_CODE,
        "debit_original": Decimal("100.0000") if debit else Decimal("0.0000"),
        "credit_original": Decimal("0.0000") if debit else Decimal("100.0000"),
        "original_currency": "KRW",
        "debit_functional": Decimal("100.0000") if debit else Decimal("0.0000"),
        "credit_functional": Decimal("0.0000") if debit else Decimal("100.0000"),
        "functional_currency": "KRW",
        "fx_rate_snapshot_id": None,
        "fx_rate_snapshot_hash": None,
        "source_record_line_ref": f"candidate-line:{line_no}",
        "description": "테스트 전표",
        "dimensions_json": {"cost_center": "HQ"},
        "evidence_hash": HASH_C,
        "line_hash": HASH_D,
    }
    value["line_hash"] = build_line_hash(value)
    return value


def _bundle() -> dict[str, object]:
    lines = [_line(1, debit=True), _line(2, debit=False)]
    header: dict[str, object] = {
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "journal_id": JOURNAL_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_hash": HASH_A,
        "period_id": PERIOD_ID,
        "posting_sequence": 1,
        "journal_no": "VO00-2026-000001",
        "state": "POSTED",
        "transaction_kind": "STANDARD",
        "recognition_date": date(2026, 11, 13),
        "posting_date": date(2026, 11, 13),
        "functional_currency": "KRW",
        "source_document_id": DOCUMENT_ID,
        "source_document_revision": 1,
        "source_document_hash": HASH_B,
        "accounting_acceptance_id": ACCEPTANCE_ID,
        "posting_rule_release_hash": HASH_C,
        "fx_rate_set_hash": HASH_D,
        "reversal_of_journal_id": None,
        "business_operation_id": OPERATION_ID,
        "idempotency_key": "journal-post-001",
        "payload_hash": HASH_E,
        "line_count": 2,
        "total_debit_functional": Decimal("100.0000"),
        "total_credit_functional": Decimal("100.0000"),
        "journal_hash": HASH_F,
        "posted_at": NOW,
    }
    header["journal_hash"] = build_journal_hash(
        header, line_hashes=[str(line["line_hash"]) for line in lines]
    )
    acceptance: dict[str, object] = {
        "tenant_id": TENANT,
        "company_id": COMPANY_ID,
        "acceptance_id": ACCEPTANCE_ID,
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": 1,
        "candidate_hash": HASH_A,
        "accounting_evidence_id": EVIDENCE_ID,
        "approval_case_id": CASE_ID,
        "purpose": "ACCOUNTING_POSTING",
        "proof_hash": HASH_B,
        "wc_decision_id": DECISION_ID,
        "oa_decision_ref": "oa-authz:accountant-current",
        "oa_decision_revision_hash": HASH_C,
        "accepted_by": "accountant-cfo",
        "accepted_at": NOW,
        "journal_id": JOURNAL_ID,
        "acceptance_hash": HASH_D,
    }
    acceptance["acceptance_hash"] = build_acceptance_hash(acceptance)
    return admit_posted_journal(
        acceptance=acceptance,
        header=header,
        lines=lines,
    )


def _rehash(bundle: dict[str, object]) -> None:
    lines = bundle["lines"]
    for line in lines:
        line["line_hash"] = build_line_hash(line)
    header = bundle["header"]
    header["journal_hash"] = build_journal_hash(
        header,
        line_hashes=[
            str(line["line_hash"])
            for line in sorted(lines, key=lambda item: item["line_no"])
        ],
    )
    acceptance = bundle["acceptance"]
    acceptance["acceptance_hash"] = build_acceptance_hash(acceptance)


def _query_service(value=None):
    authorization = AuthorizationSource()
    projects = ProjectAuthorizer()
    service = EosJournalQueryService(
        repository=StaticRepository(value or _bundle()),
        authorization_source=authorization,
        project_authorizer=projects,
        clock=lambda: NOW,
    )
    return service, authorization, projects


def _query(service, method="get"):
    return getattr(service, method)(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
        requester_subject_id="employee-1001",
        correlation_id="correlation-w40-s4-02",
    )


def test_admit_and_verify_exact_immutable_journal() -> None:
    service, _authorization, projects = _query_service()
    result = _query(service)
    assert result["schema_version"] == "eos_posted_journal.v1"
    assert result["header"]["journal_id"] == JOURNAL_ID
    assert result["header"]["total_debit_functional"] == "100.0000"
    assert [line["line_no"] for line in result["lines"]] == [1, 2]
    assert projects.calls[0]["action"] == "finance:report:read"
    assert projects.calls[0]["expected_project_code"] == PROJECT_CODE

    verification = _query(service, "verify")
    assert verification["verification_status"] == "VERIFIED"
    assert verification["line_count"] == 2
    assert verification["total_debit_functional"] == "100.0000"
    assert verification["verification_hash"].startswith("sha256:")


def test_repository_stages_and_reads_journal_without_own_transaction() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    repository = SqlAlchemyEosJournalRepository(sessions)
    bundle = _bundle()
    with sessions.begin() as session:
        repository.stage_in_session(session, **bundle)
    found = repository.get(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        journal_id=JOURNAL_ID,
    )
    assert found is not None
    assert found["header"]["journal_hash"] == bundle["header"]["journal_hash"]
    assert len(found["lines"]) == 2

    with sessions() as session:
        with pytest.raises(EosJournalError) as duplicate:
            repository.stage_in_session(session, **bundle)
        assert duplicate.value.status_code == 409
        session.rollback()

    with sessions.begin() as session:
        session.execute(delete(EOS_ACCOUNTING_APPROVAL_ACCEPTANCE_TABLE))
    with pytest.raises(EosJournalError) as corrupt:
        repository.get(tenant_id=TENANT, company_id=COMPANY_ID, journal_id=JOURNAL_ID)
    assert corrupt.value.error_code == "EOS_JOURNAL_STATE_INVALID"

    engine.dispose()
    with pytest.raises(EosJournalError) as unavailable:
        repository.get(tenant_id=TENANT, company_id=COMPANY_ID, journal_id=JOURNAL_ID)
    assert unavailable.value.error_code == "EOS_JOURNAL_PERSISTENCE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda bundle: bundle["header"].update(state="DRAFT"), "must be POSTED"),
        (
            lambda bundle: bundle["header"].update(total_credit_functional=Decimal(99)),
            "must balance",
        ),
        (lambda bundle: bundle.update(lines=bundle["lines"][:1]), "at least two"),
        (
            lambda bundle: bundle["lines"][0].update(credit_functional=Decimal(1)),
            "exactly one",
        ),
        (lambda bundle: bundle["lines"][0].update(line_hash=HASH_A), "line_hash"),
        (
            lambda bundle: bundle["acceptance"].update(purpose="DOCUMENT_SIGNOFF"),
            "ACCOUNTING_POSTING",
        ),
        (
            lambda bundle: bundle["acceptance"].update(acceptance_hash=HASH_A),
            "acceptance_hash",
        ),
        (lambda bundle: bundle["header"].update(journal_hash=HASH_A), "journal_hash"),
    ],
)
def test_admission_rejects_malformed_or_unbalanced_journal(mutation, message) -> None:
    bundle = _bundle()
    mutation(bundle)
    with pytest.raises(EosJournalError) as exc:
        admit_posted_journal(**bundle)
    assert message in exc.value.detail


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda b: b.update(lines="bad"), "ordered collection"),
        (lambda b: b["header"].update(posting_date=date(2026, 11, 12)), "precede"),
        (lambda b: b["header"].update(company_id="not-a-uuid"), "must be a UUID"),
        (lambda b: b["header"].update(posting_sequence=True), "positive integer"),
        (lambda b: b["header"].update(line_count=0), "positive integer"),
        (lambda b: b["header"].update(total_debit_functional="NaN"), "invalid amount"),
        (lambda b: b["header"].update(recognition_date=NOW), "must be a date"),
        (
            lambda b: b["header"].update(posted_at=NOW.replace(tzinfo=None)),
            "timezone-aware",
        ),
        (lambda b: b["header"].update(functional_currency="krw"), "ISO currency"),
        (lambda b: b["header"].update(candidate_hash="bad"), "sha256"),
        (lambda b: b["header"].update(unexpected="field"), "fields do not match"),
        (lambda b: b["lines"][0].update(project_code="BAD"), "project_code"),
        (lambda b: b["lines"][0].update(dimensions_json=[]), "must be an object"),
        (
            lambda b: b["lines"][0].update(
                fx_rate_snapshot_id="45000000-0000-4000-8000-000000000099"
            ),
            "Same-currency",
        ),
        (
            lambda b: b["lines"][0].update(original_currency="USD"),
            "requires an FX snapshot",
        ),
        (lambda b: b["lines"][0].update(tenant_id="OTHER"), "does not match"),
    ],
)
def test_admission_rejects_invalid_scalar_and_fx_semantics(mutation, message) -> None:
    bundle = _bundle()
    mutation(bundle)
    with pytest.raises(EosJournalError) as exc:
        admit_posted_journal(**bundle)
    assert message in exc.value.detail


def test_admission_accepts_foreign_currency_snapshot_and_sorts_lines() -> None:
    bundle = _bundle()
    bundle["lines"].reverse()
    bundle["lines"][1].update(
        original_currency="USD",
        fx_rate_snapshot_id="45000000-0000-4000-8000-000000000099",
        fx_rate_snapshot_hash=HASH_E,
    )
    _rehash(bundle)
    admitted = admit_posted_journal(**bundle)
    assert [line["line_no"] for line in admitted["lines"]] == [1, 2]
    assert admitted["lines"][0]["fx_rate_snapshot_hash"] == HASH_E


def test_admission_rejects_acceptance_identity_mismatch() -> None:
    bundle = _bundle()
    bundle["acceptance"]["acceptance_id"] = "45000000-0000-4000-8000-000000000099"
    _rehash(bundle)
    with pytest.raises(EosJournalError) as exc:
        admit_posted_journal(**bundle)
    assert "acceptance identity" in exc.value.detail


def test_verification_detects_persisted_tamper() -> None:
    bundle = _bundle()
    bundle["lines"][0]["debit_functional"] = Decimal("99.0000")
    service, _authorization, _projects = _query_service(bundle)
    with pytest.raises(EosJournalError) as exc:
        _query(service, "verify")
    assert exc.value.error_code == "EOS_JOURNAL_VERIFICATION_FAILED"
    assert "LINE_HASH_MISMATCH" in exc.value.detail
    assert "FUNCTIONAL_BALANCE_MISMATCH" in exc.value.detail


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (lambda b: b["header"].update(line_count=3), "LINE_COUNT_MISMATCH"),
        (lambda b: b["header"].update(journal_hash=HASH_A), "JOURNAL_HASH_MISMATCH"),
        (
            lambda b: b["acceptance"].update(candidate_hash=HASH_B),
            "ACCOUNTING_ACCEPTANCE_MISMATCH",
        ),
    ],
)
def test_verification_reports_each_persisted_mismatch(mutation, failure) -> None:
    bundle = _bundle()
    mutation(bundle)
    service, _authorization, _projects = _query_service(bundle)
    with pytest.raises(EosJournalError) as exc:
        _query(service, "verify")
    assert failure in exc.value.detail


@pytest.mark.parametrize(
    "configure",
    [
        lambda authorization, _projects: setattr(authorization, "active", False),
        lambda authorization, _projects: setattr(authorization, "scopes", []),
        lambda authorization, _projects: setattr(authorization, "company_ids", []),
        lambda authorization, _projects: setattr(authorization, "revision", "bad"),
        lambda authorization, _projects: setattr(
            authorization, "error", AuthorizationSubjectDenied("inactive")
        ),
        lambda _authorization, projects: setattr(
            projects,
            "error",
            EosProjectAuthorizationError(
                "OA_PROJECT_AUTHORIZATION_DENIED",
                "denied",
                status_code=403,
            ),
        ),
        lambda _authorization, projects: setattr(
            projects,
            "error",
            EosProjectAuthorizationError(
                "OA_PROJECT_AUTHORIZATION_UNAVAILABLE",
                "unavailable",
                status_code=503,
                retryable=True,
            ),
        ),
    ],
)
def test_query_fails_closed_for_oa_and_project_authorization(configure) -> None:
    service, authorization, projects = _query_service()
    configure(authorization, projects)
    with pytest.raises(EosJournalError) as exc:
        _query(service)
    assert exc.value.status_code in {403, 503}


def test_query_rejects_missing_journal_and_bad_identity() -> None:
    service, _authorization, _projects = _query_service()
    service._repository.value = None
    with pytest.raises(EosJournalError) as missing:
        _query(service)
    assert missing.value.status_code == 404

    service, _authorization, _projects = _query_service()
    with pytest.raises(EosJournalError) as invalid:
        service.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            requester_subject_id="bad subject",
            correlation_id="correlation",
        )
    assert invalid.value.status_code == 422


def test_query_rejects_malformed_oa_empty_projects_and_naive_clock() -> None:
    service, authorization, _projects = _query_service()
    authorization.effective_authorization = lambda **_kwargs: "malformed"
    with pytest.raises(EosJournalError) as malformed:
        _query(service)
    assert malformed.value.status_code == 403

    service, authorization, _projects = _query_service()
    authorization.error = RuntimeError("network")
    with pytest.raises(EosJournalError) as unavailable:
        _query(service)
    assert unavailable.value.status_code == 503

    bundle = _bundle()
    bundle["lines"] = []
    service, _authorization, _projects = _query_service(bundle)
    with pytest.raises(EosJournalError) as unscoped:
        _query(service)
    assert unscoped.value.error_code == "EOS_JOURNAL_STATE_INVALID"

    service, _authorization, _projects = _query_service()
    service._clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(EosJournalError) as bad_clock:
        _query(service, "verify")
    assert bad_clock.value.error_code == "EOS_JOURNAL_VERIFICATION_FAILED"


def test_query_rejects_invalid_correlation_before_project_authorization() -> None:
    service, _authorization, _projects = _query_service()
    with pytest.raises(EosJournalError) as invalid:
        service.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            journal_id=JOURNAL_ID,
            requester_subject_id="employee-1001",
            correlation_id="bad correlation",
        )
    assert invalid.value.status_code == 422


def test_installed_journal_routes_and_unwired_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        finance_v2_api,
        "admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(
            subject="nex-ae-api",
            audience="nex-eos",
            scopes=("service:call",),
        ),
    )
    service, _authorization, _projects = _query_service()
    app = FastAPI()
    register_finance_v2_routes(app)
    app.state.eos_journal_query_service = service
    headers = {
        "Authorization": "Bearer service-token",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Company-Id": COMPANY_ID,
        "X-NeX-Subject-Id": "employee-1001",
        "X-Correlation-Id": "correlation-w40-s4-02",
    }
    with TestClient(app) as client:
        get_response = client.get(
            f"/internal/v2/finance/journals/{JOURNAL_ID}", headers=headers
        )
        verify_response = client.get(
            f"/internal/v2/finance/journals/{JOURNAL_ID}/verification",
            headers=headers,
        )
    assert get_response.status_code == 200
    assert verify_response.status_code == 200

    del app.state.eos_journal_query_service
    with TestClient(app) as client:
        unavailable = client.get(
            f"/internal/v2/finance/journals/{JOURNAL_ID}", headers=headers
        )
    assert unavailable.status_code == 503
