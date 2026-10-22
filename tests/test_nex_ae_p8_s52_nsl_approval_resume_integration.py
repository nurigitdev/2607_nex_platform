from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from nex_ae_api.nsl_approval_resume_integration import (
    NslApprovalResumeIntegration,
    NslApprovalResumeIntegrationError,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_ae_api.platform_approval_evidence import build_platform_approval_evidence
from nex_ae_api.runtime_jobs import RuntimeJobClaim

HASH = "sha256:" + "a" * 64
TENANT = "tenant-p8-s52"
RUNTIME_JOB_ID = "11111111-1111-4111-8111-111111111152"
AGENT_EXECUTION_ID = "22222222-2222-4222-8222-222222222252"
STEP_ID = "step-p8-s52"
REQUEST_ID = "approval-request-p8-s52"
WORK_ITEM_ID = "33333333-3333-4333-8333-333333333352"
NSL_EXECUTION_ID = "nsl-execution-p8-s52"
BUSINESS_OPERATION_ID = "business-operation-p8-s52"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class ApprovalEvidence:
    tenant_id: str
    execution_id: str
    business_operation_id: str
    approval_id: str
    approval_request_id: str
    skill_semantic_hash: str
    decision: Decision
    approver_id: str
    decided_at: datetime
    expires_at: datetime | None
    payload_hash: str
    write_intent_hash: str
    evidence_integrity: str


@dataclass(frozen=True)
class ResumeToken:
    execution_id: str
    business_operation_id: str
    checkpoint_version: int
    approval_evidence: ApprovalEvidence


class Coordinator:
    calls: ClassVar[list[dict[str, Any]]] = []

    async def resume(self, **values: Any) -> object:
        type(self).calls.append(values)
        return SimpleNamespace(validation="VALID", claim_consumed=True)


class Request:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def to_data(self) -> dict[str, object]:
        return dict(self._value)


class Source:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def resolve(self, _claim: object) -> object:
        return copy.deepcopy(self.value)

    def load_request(self, **values: object) -> object:
        self.calls.append(values)
        return copy.deepcopy(self.value)

    def get(self, **values: object) -> object:
        self.calls.append(values)
        return copy.deepcopy(self.value)


def _request() -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": REQUEST_ID,
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": "sha256:" + "b" * 64,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": "sha256:" + "c" * 64,
        "write_intent_hash": "write-intent-p8-s52",
        "risk_level": "R3",
        "message": "Create voucher draft.",
        "expires_at": "2026-10-23T12:00:00Z",
        "display_safe_summary": {"line_count": 2},
        "protected_payload_ref": "snapshot://private/p8-s52",
        "data_classification": "CONFIDENTIAL",
    }


def _evidence() -> dict[str, Any]:
    request = _request()
    protected_ref = "ae://nsl-approval-requests/ab/" + "d" * 64 + ".json"
    protected = {
        "tenant_id": TENANT,
        "approval_request_id": REQUEST_ID,
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "protected_request_ref": protected_ref,
        "approval_request_hash": "sha256:" + "e" * 64,
    }
    wait = {
        "tenant_id": TENANT,
        "agent_execution_id": AGENT_EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_type": "NSL_APPROVAL",
        "external_ref": REQUEST_ID,
        "state": "RESUME_QUEUED",
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "approval_request_id": REQUEST_ID,
        "checkpoint_version": 7,
    }
    work_item = {
        "tenant_id": TENANT,
        "approval_work_item_id": WORK_ITEM_ID,
        "approval_domain": "NSL_WRITE",
        "approval_provider_type": "NSL",
        "source_ref": REQUEST_ID,
        "approval_target_ref": REQUEST_ID,
        "semantic_hash": protected["approval_request_hash"],
        "agent_execution_id": AGENT_EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "approval_request_id": REQUEST_ID,
        "protected_request_ref": protected_ref,
        "state": "APPROVED",
        "expires_at": request["expires_at"],
    }
    decision = {
        "tenant_id": TENANT,
        "decision_id": "44444444-4444-4444-8444-444444444452",
        "approval_work_item_id": WORK_ITEM_ID,
        "decision": "APPROVE",
        "decided_by": "employee-1004",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-authz:" + "f" * 64,
        "authorization_revision_hash": "sha256:" + "f" * 64,
        "authorization_checked_at": "2026-10-22T11:59:00Z",
        "decided_at": "2026-10-22T12:00:00Z",
    }
    return build_platform_approval_evidence(
        approval_request=Request(request),
        protected_request=protected,
        wait_registration=wait,
        approval_work_item=work_item,
        approval_decision=decision,
        created_at=datetime(2026, 10, 22, 12, 1, tzinfo=UTC),
    )


def _authority(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ae_nsl_approval_resume_authority.v1",
        "tenant_id": TENANT,
        "runtime_job_id": RUNTIME_JOB_ID,
        "agent_execution_id": AGENT_EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "wait_id": "wait-p8-s52",
        "event_id": "event-p8-s52",
        "approval_request_id": REQUEST_ID,
        "approval_work_item_ref": WORK_ITEM_ID,
        "nsl_execution_id": NSL_EXECUTION_ID,
        "business_operation_id": BUSINESS_OPERATION_ID,
        "evidence_integrity": evidence["evidence_integrity"],
        "approval_evidence_ref": f"ae-approval-evidence:{REQUEST_ID}",
        "resume_token_ref": f"ae-nsl-resume:{evidence['evidence_integrity']}",
        "checkpoint_version": 7,
        "event": {},
    }


def _adapter(
    *, token_type: object = ResumeToken, coordinator_type: object = Coordinator
) -> NslV02PublicApiAdapter:
    symbols = [
        object,
        ApprovalEvidence,
        object,
        coordinator_type,
        token_type,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
    ]
    return NslV02PublicApiAdapter(*symbols, HASH, HASH)


def _integration(
    *,
    authority: object | None = None,
    request: object | None = None,
    evidence: object | None = None,
    adapter: NslV02PublicApiAdapter | None = None,
) -> tuple[NslApprovalResumeIntegration, Source, Source]:
    canonical_evidence = _evidence()
    request_source = Source(_request() if request is None else request)
    evidence_source = Source(
        canonical_evidence if evidence is None else evidence
    )
    return (
        NslApprovalResumeIntegration(
            authority_source=Source(
                _authority(canonical_evidence) if authority is None else authority
            ),
            request_source=request_source,
            evidence_source=evidence_source,
            public_api=adapter or _adapter(),
        ),
        request_source,
        evidence_source,
    )


def _claim() -> RuntimeJobClaim:
    return RuntimeJobClaim(job={}, attempt={})


def test_resume_invokes_admitted_coordinator_with_only_persisted_identity() -> None:
    Coordinator.calls.clear()
    integration, request_source, evidence_source = _integration()
    skill = object()
    request = object()
    checkpoint_port = object()
    verifier = object()
    clock = object()
    runtime_clock = object()

    invocation = asyncio.run(
        integration.resume(
            _claim(),
            skill=skill,
            request=request,
            checkpoint_port=checkpoint_port,
            verifier=verifier,
            clock=clock,
            runtime_clock=runtime_clock,
        )
    )

    assert invocation.runtime_job_id == invocation.claim_id == RUNTIME_JOB_ID
    assert invocation.nsl_execution_id == NSL_EXECUTION_ID
    assert invocation.business_operation_id == BUSINESS_OPERATION_ID
    assert invocation.checkpoint_version == 7
    assert invocation.approval_request_id == REQUEST_ID
    assert invocation.resume_token.execution_id == NSL_EXECUTION_ID
    assert invocation.resume_token.business_operation_id == BUSINESS_OPERATION_ID
    assert invocation.resume_token.checkpoint_version == 7
    assert invocation.resume_token.approval_evidence.decision is Decision.APPROVED
    assert invocation.outcome.claim_consumed is True
    assert request_source.calls == [
        {"tenant_id": TENANT, "approval_request_id": REQUEST_ID}
    ]
    assert evidence_source.calls == request_source.calls
    assert Coordinator.calls == [
        {
            "token": invocation.resume_token,
            "skill": skill,
            "request": request,
            "approval_id": "APPROVE_VOUCHER_DRAFT",
            "write_node_id": "write-voucher-draft",
            "current_write_intent_hash": "write-intent-p8-s52",
            "current_payload_hash": "sha256:" + "c" * 64,
            "claim_id": RUNTIME_JOB_ID,
            "checkpoint_port": checkpoint_port,
            "verifier": verifier,
            "clock": clock,
            "runtime_clock": runtime_clock,
        }
    ]


def test_requires_admitted_public_api_and_safe_error_string() -> None:
    with pytest.raises(NslApprovalResumeIntegrationError) as error:
        NslApprovalResumeIntegration(
            authority_source=Source({}),
            request_source=Source({}),
            evidence_source=Source({}),
            public_api=object(),  # type: ignore[arg-type]
        )
    assert error.value.error_code == "ae.nsl_approval_resume_integration_invalid"
    assert str(error.value) == error.value.detail


@pytest.mark.parametrize("missing", ("request", "evidence"))
def test_missing_request_or_evidence_fails_closed(missing: str) -> None:
    integration, _, _ = _integration(
        request=None if missing == "request" else _request(),
        evidence=None if missing == "evidence" else _evidence(),
    )
    if missing == "request":
        integration._request_source.value = None  # type: ignore[attr-defined]
    else:
        integration._evidence_source.value = None  # type: ignore[attr-defined]

    with pytest.raises(NslApprovalResumeIntegrationError) as error:
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )
    assert error.value.error_code.endswith("authority_missing")


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("authority", "schema_version", "bad"),
        ("authority", "tenant_id", ""),
        ("authority", "checkpoint_version", 0),
        ("authority", "checkpoint_version", True),
        ("authority", "nsl_execution_id", "other"),
        ("authority", "approval_work_item_ref", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ("authority", "approval_evidence_ref", "other"),
        ("request", "business_operation_id", "other"),
        ("request", "payload_hash", "sha256:" + "9" * 64),
    ),
)
def test_all_persisted_lineage_drift_fails_before_coordinator(
    target: str, field: str, value: object
) -> None:
    evidence = _evidence()
    authority = _authority(evidence)
    request = _request()
    if target == "authority":
        authority[field] = value
    elif target == "request":
        request[field] = value
    else:
        evidence[field] = value
    integration, _, _ = _integration(
        authority=authority, request=request, evidence=evidence
    )

    with pytest.raises((NslApprovalResumeIntegrationError, ValueError)):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )


def test_incompatible_token_and_coordinator_fail_closed() -> None:
    class MutatingToken(ResumeToken):
        def __getattribute__(self, name: str) -> object:
            if name == "execution_id":
                return "other"
            return super().__getattribute__(name)

    integration, _, _ = _integration(adapter=_adapter(token_type=MutatingToken))
    with pytest.raises(NslApprovalResumeIntegrationError):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )

    integration, _, _ = _integration(adapter=_adapter(coordinator_type=object))
    with pytest.raises(NslApprovalResumeIntegrationError):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )

    class RaisingToken:
        def __init__(self, **_values: object) -> None:
            raise TypeError("incompatible")

    integration, _, _ = _integration(adapter=_adapter(token_type=RaisingToken))
    with pytest.raises(NslApprovalResumeIntegrationError):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )

    class RaisingCoordinator:
        def __init__(self) -> None:
            raise ValueError("incompatible")

    integration, _, _ = _integration(
        adapter=_adapter(coordinator_type=RaisingCoordinator)
    )
    with pytest.raises(NslApprovalResumeIntegrationError):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )


def test_non_object_authority_fails_closed() -> None:
    integration, _, _ = _integration(authority=[])

    with pytest.raises(NslApprovalResumeIntegrationError):
        asyncio.run(
            integration.resume(
                _claim(),
                skill=object(),
                request=object(),
                checkpoint_port=object(),
                verifier=object(),
                clock=object(),
            )
        )


def test_coordinator_domain_outcome_is_not_reinterpreted() -> None:
    class RejectedCoordinator:
        async def resume(self, **_values: object) -> object:
            return SimpleNamespace(validation="VALID_REJECTED", claim_consumed=True)

    integration, _, _ = _integration(
        adapter=_adapter(coordinator_type=RejectedCoordinator)
    )

    invocation = asyncio.run(
        integration.resume(
            _claim(),
            skill=object(),
            request=object(),
            checkpoint_port=object(),
            verifier=object(),
            clock=object(),
        )
    )

    assert invocation.outcome.validation == "VALID_REJECTED"
    assert invocation.outcome.claim_consumed is True
