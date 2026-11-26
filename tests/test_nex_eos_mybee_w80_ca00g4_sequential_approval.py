from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nex_eos import EOS_METADATA
from nex_eos.business_proposal_lifecycle import EosBusinessProposalLifecycleService
from nex_eos.business_proposals import (
    BusinessProposalRevisionInput,
    BusinessProposalSubmissionInput,
    EosBusinessProposalError,
    EosBusinessProposalSignoffObserver,
    SqlAlchemyEosBusinessProposalRepository,
)
from nex_eos.scoped_approvals import EosScopedApprovalError, _stage_nominations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
PROPOSAL_ID = "d1000000-0000-4000-8000-000000000041"
COMPANY_ID = "d2000000-0000-4000-8000-000000000041"
PROJECT_ID = "d3000000-0000-4000-8000-000000000041"
POLICY_ID = "d4000000-0000-4000-8000-000000000041"
REQUESTER = "employee-8201"
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


class CapturingScopedApprovalService:
    def __init__(self) -> None:
        self.payload = None

    def request_case(self, payload, *, caller):
        self.payload = payload
        case = payload["case"]
        return {
            "schema_version": "eos_scoped_approval_request_receipt.v2",
            "scoped_approval_case": {
                "case_id": case["case_id"],
                "target_approver_ref": case["stage_nominations"][0]["subject_id"],
            },
            "caller_subject": caller.subject,
        }


def _runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    repository = SqlAlchemyEosBusinessProposalRepository(sessions)
    return engine, sessions, repository


def _draft() -> BusinessProposalRevisionInput:
    return BusinessProposalRevisionInput(
        tenant_id=TENANT,
        proposal_id=PROPOSAL_ID,
        revision_id=str(uuid.uuid4()),
        company_id=COMPANY_ID,
        requester_subject_id=REQUESTER,
        document_type="BUSINESS_PROPOSAL",
        work_code="FL0004011",
        title="외부 용역비 사용 품의",
        purpose="프로젝트 외부 용역비 집행",
        business_justification="납기 준수를 위한 외부 전문 인력 투입",
        transaction_type="EXTERNAL_LABOR",
        requested_amount=Decimal("2500000"),
        original_currency="KRW",
        valid_from=NOW,
        valid_until=NOW + timedelta(days=30),
        scope_type="PROJECT",
        project_ids=(PROJECT_ID,),
        project_codes=("VO00D260001",),
    )


def _line():
    return (
        {
            "stage_order": 1,
            "position_type": "TEAM_LEAD",
            "subject_id": "approver-team",
            "display_name": "Team Lead",
            "authority_hash": "sha256:" + "b" * 64,
        },
        {
            "stage_order": 2,
            "position_type": "GROUP_LEAD",
            "subject_id": "approver-group",
            "display_name": "Group Lead",
            "authority_hash": "sha256:" + "c" * 64,
        },
    )


def _submission(created):
    return BusinessProposalSubmissionInput(
        tenant_id=TENANT,
        proposal_id=PROPOSAL_ID,
        requester_subject_id=REQUESTER,
        expected_version=created["version"],
        expected_revision=created["current_revision_no"],
        content_hash=created["current_revision"]["content_hash"],
        approval_policy_id=POLICY_ID,
        approval_policy_hash=HASH,
        approval_preview_hash="sha256:" + "d" * 64,
        candidate_evidence_hash="sha256:" + "e" * 64,
        approval_line_hash="sha256:" + "f" * 64,
        approval_line=_line(),
        normalized_amount=Decimal("2500000"),
        functional_currency="KRW",
        normalization_hash="sha256:" + "1" * 64,
    )


def test_submission_materializes_generic_nominations_and_binds_case() -> None:
    engine, _sessions, repository = _runtime()
    created = repository.create_draft(_draft(), created_at=NOW)
    scoped = CapturingScopedApprovalService()
    service = EosBusinessProposalLifecycleService(
        proposals=repository,
        scoped_approvals=scoped,
    )

    result = service.submit(_submission(created), submitted_at=NOW)

    assert result["state"] == "SUBMITTED"
    assert result["approval_case_id"] is not None
    case = scoped.payload["case"]
    assert [item["subject_id"] for item in case["stage_nominations"]] == [
        "approver-team",
        "approver-group",
    ]
    assert {item["approval_line_hash"] for item in case["stage_nominations"]} == {
        "sha256:" + "f" * 64
    }
    assert case["document_signoff_context"]["approved_document_id"] == PROPOSAL_ID
    assert case["document_signoff_context"]["allowed_project_codes"] == [
        "VO00D260001"
    ]
    engine.dispose()


def test_terminal_observer_rejects_and_replays_exact_proposal_lineage() -> None:
    engine, sessions, repository = _runtime()
    created = repository.create_draft(_draft(), created_at=NOW)
    scoped = CapturingScopedApprovalService()
    result = EosBusinessProposalLifecycleService(
        proposals=repository,
        scoped_approvals=scoped,
    ).submit(_submission(created), submitted_at=NOW)
    observer = EosBusinessProposalSignoffObserver(repository)
    case = scoped.payload["case"]
    context = case["document_signoff_context"]

    with sessions.begin() as session:
        rejected = observer.apply_in_session(
            session,
            case={**case, "case_id": result["approval_case_id"]},
            context=context,
            state="REJECTED",
            envelope_id=None,
            decided_at=NOW + timedelta(minutes=3),
        )
    with sessions.begin() as session:
        replay = observer.apply_in_session(
            session,
            case={**case, "case_id": result["approval_case_id"]},
            context=context,
            state="REJECTED",
            envelope_id=None,
            decided_at=NOW + timedelta(minutes=3),
        )

    assert rejected["state"] == replay["state"] == "REJECTED"
    assert rejected["approved_envelope_id"] is None
    engine.dispose()


def test_resume_recovers_post_submit_pre_bind_failure_and_rejects_drift() -> None:
    engine, _sessions, repository = _runtime()
    created = repository.create_draft(_draft(), created_at=NOW)
    repository.submit(_submission(created), submitted_at=NOW)
    scoped = CapturingScopedApprovalService()
    service = EosBusinessProposalLifecycleService(
        proposals=repository,
        scoped_approvals=scoped,
    )
    requested = [
        {"stage_order": item["stage_order"], "subject_id": item["subject_id"]}
        for item in _line()
    ]

    recovered = service.resume(
        tenant_id=TENANT,
        proposal_id=PROPOSAL_ID,
        requester_subject_id=REQUESTER,
        expected_revision=1,
        expected_preview_hash="sha256:" + "d" * 64,
        selected_approvers=requested,
    )
    replay = service.resume(
        tenant_id=TENANT,
        proposal_id=PROPOSAL_ID,
        requester_subject_id=REQUESTER,
        expected_revision=1,
        expected_preview_hash="sha256:" + "d" * 64,
        selected_approvers=requested,
    )

    assert recovered["approval_case_id"] == replay["approval_case_id"]
    assert recovered["version"] == replay["version"]
    with pytest.raises(EosBusinessProposalError, match="revision conflicts"):
        service.resume(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id=REQUESTER,
            expected_revision=2,
            expected_preview_hash="sha256:" + "d" * 64,
            selected_approvers=requested,
        )
    with pytest.raises(EosBusinessProposalError, match="preview conflicts"):
        service.resume(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id=REQUESTER,
            expected_revision=1,
            expected_preview_hash="sha256:" + "9" * 64,
            selected_approvers=requested,
        )
    with pytest.raises(EosBusinessProposalError, match="approval line conflicts"):
        service.resume(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id=REQUESTER,
            expected_revision=1,
            expected_preview_hash="sha256:" + "d" * 64,
            selected_approvers=[
                {"stage_order": 1, "subject_id": "different-approver"}
            ],
        )
    engine.dispose()


def test_resume_rejects_missing_or_unsubmitted_proposal() -> None:
    engine, _sessions, repository = _runtime()
    repository.create_draft(_draft(), created_at=NOW)
    service = EosBusinessProposalLifecycleService(
        proposals=repository,
        scoped_approvals=CapturingScopedApprovalService(),
    )

    with pytest.raises(EosBusinessProposalError, match="identity was not found"):
        service.resume(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id="another-requester",
            expected_revision=1,
            expected_preview_hash="sha256:" + "d" * 64,
            selected_approvers=[],
        )
    with pytest.raises(EosBusinessProposalError, match="not an admitted submission"):
        service.resume(
            tenant_id=TENANT,
            proposal_id=PROPOSAL_ID,
            requester_subject_id=REQUESTER,
            expected_revision=1,
            expected_preview_hash="sha256:" + "d" * 64,
            selected_approvers=[],
        )
    engine.dispose()


def test_stage_nomination_contract_rejects_policy_and_sod_drift() -> None:
    stages = [
        {"stage_order": 1, "position_type": "TEAM_LEAD"},
        {"stage_order": 2, "position_type": "GROUP_LEAD"},
    ]
    valid = [
        {
            "stage_order": item["stage_order"],
            "position_type": item["position_type"],
            "subject_id": f"approver-{item['stage_order']}",
            "authority_hash": "sha256:" + str(item["stage_order"]) * 64,
            "approval_line_hash": HASH,
        }
        for item in stages
    ]

    assert len(_stage_nominations(valid, stages=stages, requester_id=REQUESTER)) == 2
    invalid_values = (
        "not-an-array",
        valid[:1],
        ["not-an-object", valid[1]],
        [{**valid[0], "unexpected": True}, valid[1]],
        [{**valid[0], "position_type": "WRONG_ROLE"}, valid[1]],
        [{**valid[0], "subject_id": REQUESTER}, valid[1]],
        [valid[0], {**valid[1], "approval_line_hash": "sha256:" + "9" * 64}],
    )
    for value in invalid_values:
        with pytest.raises(EosScopedApprovalError):
            _stage_nominations(value, stages=stages, requester_id=REQUESTER)
