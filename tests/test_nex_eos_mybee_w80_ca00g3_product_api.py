from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_METADATA,
    BusinessProposalRevisionInput,
    BusinessProposalSubmissionInput,
    EosBusinessProposalError,
    SqlAlchemyEosBusinessProposalRepository,
)
from nex_eos.business_proposal_api import register_business_proposal_routes
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "VO00"
PROPOSAL_ID = "d1000000-0000-4000-8000-000000000031"
COMPANY_ID = "d2000000-0000-4000-8000-000000000031"
PROJECT_ID = "d3000000-0000-4000-8000-000000000031"
POLICY_ID = "d4000000-0000-4000-8000-000000000031"
REQUESTER = "employee-8101"
NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield SqlAlchemyEosBusinessProposalRepository(factory)
    engine.dispose()


def _draft() -> BusinessProposalRevisionInput:
    return BusinessProposalRevisionInput(
        tenant_id=TENANT,
        proposal_id=PROPOSAL_ID,
        revision_id=str(uuid.uuid4()),
        company_id=COMPANY_ID,
        requester_subject_id=REQUESTER,
        document_type="EXPENSE_PROPOSAL",
        work_code="FL0004001",
        title="외부 용역비 사용 품의",
        purpose="프로젝트 외부 용역비 집행",
        business_justification="납기 준수를 위해 외부 전문 인력이 필요합니다.",
        transaction_type="EXTERNAL_LABOR",
        requested_amount=Decimal(1000000),
        original_currency="KRW",
        valid_from=NOW,
        valid_until=NOW + timedelta(days=30),
        scope_type="PROJECT",
        project_ids=(PROJECT_ID,),
        project_codes=("VO00D260001",),
        attachment_manifest=(),
    )


def _submission(created: dict[str, Any], **overrides) -> BusinessProposalSubmissionInput:
    values = {
        "tenant_id": TENANT,
        "proposal_id": PROPOSAL_ID,
        "requester_subject_id": REQUESTER,
        "expected_version": created["version"],
        "expected_revision": created["current_revision_no"],
        "content_hash": created["current_revision"]["content_hash"],
        "approval_policy_id": POLICY_ID,
        "approval_policy_hash": HASH,
        "approval_preview_hash": "sha256:" + "b" * 64,
        "candidate_evidence_hash": "sha256:" + "c" * 64,
        "approval_line_hash": "sha256:" + "d" * 64,
        "normalized_amount": Decimal(1000000),
        "functional_currency": "KRW",
        "normalization_hash": "sha256:" + "e" * 64,
    }
    values.update(overrides)
    return BusinessProposalSubmissionInput(**values)


def test_submit_binds_exact_revision_and_is_replay_safe(repository) -> None:
    created = repository.create_draft(_draft(), created_at=NOW)
    command = _submission(created)
    submitted = repository.submit(command, submitted_at=NOW)
    replay = repository.submit(command, submitted_at=NOW + timedelta(minutes=1))

    assert submitted == replay
    assert submitted["state"] == "SUBMITTED"
    assert submitted["submitted_revision_no"] == 1
    assert submitted["approval_policy_id"] == POLICY_ID
    assert submitted["approval_line_hash"] == "sha256:" + "d" * 64
    assert submitted["normalized_amount"] == "1000000.0000"
    with pytest.raises(EosBusinessProposalError) as conflict:
        repository.submit(
            _submission(created, approval_line_hash="sha256:" + "f" * 64),
            submitted_at=NOW,
        )
    assert conflict.value.error_code == "BUSINESS_PROPOSAL_CONFLICT"


@pytest.mark.parametrize(
    "overrides,error_code",
    (
        ({"requester_subject_id": "another-user"}, "BUSINESS_PROPOSAL_FORBIDDEN"),
        ({"expected_version": 2}, "BUSINESS_PROPOSAL_STALE"),
        ({"expected_revision": 2}, "BUSINESS_PROPOSAL_STALE"),
        ({"content_hash": "sha256:" + "f" * 64}, "BUSINESS_PROPOSAL_STALE"),
    ),
)
def test_submit_rejects_owner_and_stale_binding(repository, overrides, error_code) -> None:
    created = repository.create_draft(_draft(), created_at=NOW)
    with pytest.raises(EosBusinessProposalError) as caught:
        repository.submit(_submission(created, **overrides), submitted_at=NOW)
    assert caught.value.error_code == error_code


@dataclass
class FakeRepository:
    result: dict[str, Any]
    submitted: BusinessProposalSubmissionInput | None = None

    def create_draft(self, value):
        return self.result

    def revise_draft(self, value, **kwargs):
        return self.result

    def get(self, **kwargs):
        return self.result

    def list_owner(self, **kwargs):
        return [self.result]

    def submit(self, value, **kwargs):
        self.submitted = value
        return self.result


class FakeApprovalService:
    def preview(self, **kwargs):
        return {
            "tenant_id": TENANT,
            "proposal_id": PROPOSAL_ID,
            "revision_no": 1,
            "proposal_version": 1,
            "content_hash": HASH,
            "approval_policy_id": POLICY_ID,
            "approval_policy_hash": HASH,
            "preview_hash": "sha256:" + "b" * 64,
            "candidate_evidence_hash": "sha256:" + "c" * 64,
            "normalized_amount_evidence": {
                "normalized_amount": "1000000.0000",
                "functional_currency": "KRW",
                "calculation_hash": "sha256:" + "e" * 64,
            },
            "required_stages": [],
        }

    def select_line(self, **kwargs):
        return {"approval_line_hash": "sha256:" + "d" * 64, "approvers": []}


def _api_client() -> tuple[TestClient, FakeRepository]:
    aggregate = {
        "proposal_id": PROPOSAL_ID,
        "company_id": COMPANY_ID,
        "requester_subject_id": REQUESTER,
        "state": "DRAFT",
        "version": 1,
        "current_revision_no": 1,
        "current_revision": {
            "revision_no": 1,
            "content_hash": HASH,
        },
    }
    repository = FakeRepository(aggregate)
    app = FastAPI()
    app.state.eos_business_proposals = repository
    app.state.eos_business_proposal_approval = FakeApprovalService()
    register_business_proposal_routes(app)
    return TestClient(app), repository


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-eos",
        scopes=(DEFAULT_SERVICE_SCOPE,),
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT,
        "X-NeX-Subject-Id": REQUESTER,
    }


def test_product_api_exposes_owner_scoped_lifecycle_and_submit_binding() -> None:
    client, repository = _api_client()
    listed = client.get(
        "/internal/v2/business-proposals?states=DRAFT", headers=_headers()
    )
    submitted = client.post(
        f"/internal/v2/business-proposals/{PROPOSAL_ID}:submit",
        headers=_headers(),
        json={
            "effective_at": NOW.isoformat(),
            "expected_version": 1,
            "expected_revision": 1,
            "preview_hash": "sha256:" + "b" * 64,
            "selected_approvers": [],
        },
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["proposal_id"] == PROPOSAL_ID
    assert submitted.status_code == 200
    assert repository.submitted is not None
    assert repository.submitted.approval_line_hash == "sha256:" + "d" * 64


def test_product_api_fails_closed_for_missing_trust_and_dependencies() -> None:
    client, _ = _api_client()
    assert client.get(
        "/internal/v2/business-proposals",
        headers={
            "X-NeX-Tenant-Id": TENANT,
            "X-NeX-Subject-Id": REQUESTER,
        },
    ).status_code == 401
    app = FastAPI()
    app.state.eos_business_proposals = None
    app.state.eos_business_proposal_approval = None
    register_business_proposal_routes(app)
    unavailable = TestClient(app).get(
        "/internal/v2/business-proposals", headers=_headers()
    )
    assert unavailable.status_code == 503


def test_product_api_openapi_contract_covers_the_review_workspace_commands() -> None:
    spec = yaml.safe_load(
        (ROOT / "contracts/openapi/nex-eos.openapi.yaml").read_text(encoding="utf-8")
    )
    paths = spec["paths"]
    assert paths["/internal/v2/business-proposals"]["get"]["operationId"] == (
        "BUSINESS.PROPOSAL.LIST"
    )
    assert paths["/internal/v2/business-proposals"]["post"]["operationId"] == (
        "BUSINESS.PROPOSAL.CREATE"
    )
    assert paths["/internal/v2/business-proposals/{proposal_id}"]["patch"][
        "operationId"
    ] == "BUSINESS.PROPOSAL.REVISE"
    assert paths[
        "/internal/v2/business-proposals/{proposal_id}:preview-approval"
    ]["post"]["operationId"] == "BUSINESS.PROPOSAL.PREVIEW_APPROVAL"
    assert paths[
        "/internal/v2/business-proposals/{proposal_id}:select-approval-line"
    ]["post"]["operationId"] == "BUSINESS.PROPOSAL.SELECT_APPROVAL_LINE"
    assert paths["/internal/v2/business-proposals/{proposal_id}:submit"]["post"][
        "operationId"
    ] == "BUSINESS.PROPOSAL.SUBMIT"
