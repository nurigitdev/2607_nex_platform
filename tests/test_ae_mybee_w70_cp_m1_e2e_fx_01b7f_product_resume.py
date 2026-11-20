from __future__ import annotations

import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError

import nex_ae_api.approval_decision_event_api as approval_api
import pytest
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventError,
    EosProductApprovalReceiptAdmission,
    HttpEosBusinessApprovalDecisionClient,
)
from nex_ae_api.product_planning_runtime import (
    ProductPlanningRuntimeError,
    SqlAlchemyProductPlanningLineageSource,
)

TENANT = "VO00"
CASE_ID = "71000000-0000-4000-8000-000000000001"
CHECKPOINT_ID = "71000000-0000-4000-8000-000000000002"
WORK_ITEM_ID = "71000000-0000-4000-8000-000000000003"
DECISION_ID = "71000000-0000-4000-8000-000000000004"
EVENT_ID = "71000000-0000-4000-8000-000000000005"
OUTBOX_ID = "71000000-0000-4000-8000-000000000006"
ENVELOPE_ID = "71000000-0000-4000-8000-000000000007"
EVIDENCE_ID = "71000000-0000-4000-8000-000000000008"
HASH = "sha256:" + "7" * 64


def _delivery(*, decision: str = "APPROVE") -> dict[str, object]:
    occurred_at = "2026-11-19T01:02:03Z"
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": OUTBOX_ID,
        "work_item": {
            "tenant_id": TENANT,
            "approval_work_item_id": WORK_ITEM_ID,
            "approval_domain": "BUSINESS_FORMAL",
            "resume_target_ref": f"eos.scoped-approval-case:{CASE_ID}:stage:1",
        },
        "decision": {
            "tenant_id": TENANT,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
            "decision": decision,
            "decided_at": occurred_at,
        },
        "event": {
            "tenant_id": TENANT,
            "event_id": EVENT_ID,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
            "occurred_at": occurred_at,
        },
    }


def _document_receipt(*, state: str = "APPROVED") -> dict[str, object]:
    return {
        "schema_version": "eos_document_signoff_decision_receipt.v1",
        "created": True,
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "purpose": "DOCUMENT_SIGNOFF",
        "case_id": CASE_ID,
        "case_state": state,
        "next_stage_publication": None,
        "document_signoff_evidence": (
            {"evidence_id": EVIDENCE_ID} if state == "APPROVED" else None
        ),
        "approved_document_envelope": (
            {"envelope_id": ENVELOPE_ID} if state == "APPROVED" else None
        ),
    }


def _accounting_receipt() -> dict[str, object]:
    return {
        "schema_version": "eos_accounting_approval_decision_receipt.v2",
        "created": True,
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "purpose": "ACCOUNTING_POSTING",
        "case_id": CASE_ID,
        "case_state": "APPROVED",
        "observation_state": "APPROVED_PENDING_POST",
        "next_stage_publication": None,
        "accounting_approval_evidence": {"evidence_id": EVIDENCE_ID},
    }


def _wait_context(*, authority_kind: str = "BUSINESS_FORMAL") -> dict[str, object]:
    return {
        "wait": {"state": "PENDING"},
        "product_binding": {
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": HASH,
            "coordinator_id": "mybee.finance.transaction-preparation",
            "coordinator_version": "1.0.0",
            "coordinator_registration_hash": HASH,
            "expected_event_type": (
                "BUSINESS_APPROVAL_CHANGED"
                if authority_kind == "BUSINESS_FORMAL"
                else "ACCOUNTING_APPROVAL_CHANGED"
            ),
            "authority_kind": authority_kind,
            "authority_ref": CASE_ID,
        },
        "checkpoint": {"checkpoint_id": CHECKPOINT_ID},
    }


class _EosClient:
    def __init__(self, receipt: dict[str, object]) -> None:
        self.receipt = receipt
        self.calls = 0

    def ingest(self, _delivery):
        self.calls += 1
        return deepcopy(self.receipt)


class _Waits:
    def __init__(self, context: dict[str, object] | None) -> None:
        self.context = context
        self.calls: list[dict[str, str]] = []

    def resolve_product_wait_context(self, **values):
        self.calls.append(values)
        return deepcopy(self.context)


class _Events:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def ingest(self, payload):
        self.calls.append(dict(payload))
        return {
            "event_state": "MATCHED",
            "wait_state": "RESUME_QUEUED",
            "resume_runtime_job_id": "resume-job-1",
        }


def _admission(receipt, *, context=None, events=None):
    eos = _EosClient(receipt)
    waits = _Waits(context if context is not None else _wait_context())
    sink = events if events is not None else _Events()
    return (
        EosProductApprovalReceiptAdmission(
            eos_client=eos,
            wait_contexts=waits,
            product_events=sink,
        ),
        eos,
        waits,
        sink,
    )


def test_7f_document_approval_binds_wait_and_replays_exactly() -> None:
    admission, eos, waits, events = _admission(_document_receipt())

    first = admission.ingest(_delivery())
    replay = admission.ingest(_delivery())

    assert first == replay
    assert first["product_resume"]["resume_runtime_job_id"] == "resume-job-1"
    assert eos.calls == 2
    assert (
        waits.calls
        == [
            {
                "tenant_id": TENANT,
                "authority_kind": "BUSINESS_FORMAL",
                "authority_ref": CASE_ID,
            }
        ]
        * 2
    )
    assert events.calls[0] == events.calls[1]
    assert events.calls[0]["authority_evidence_ref"] == ENVELOPE_ID
    assert events.calls[0]["authority_state"] == "APPROVED"


def test_7f_accounting_approval_uses_accounting_authority_binding() -> None:
    admission, _eos, waits, events = _admission(
        _accounting_receipt(),
        context=_wait_context(authority_kind="ACCOUNTING_REVIEW"),
    )

    receipt = admission.ingest(_delivery())

    assert receipt["product_resume"]["event_state"] == "MATCHED"
    assert waits.calls[0]["authority_kind"] == "ACCOUNTING_REVIEW"
    assert events.calls[0]["authority_evidence_ref"] == EVIDENCE_ID


def test_7f_pending_stage_does_not_resume_product_wait() -> None:
    admission, _eos, waits, events = _admission(_document_receipt(state="PENDING"))

    receipt = admission.ingest(_delivery())

    assert "product_resume" not in receipt
    assert waits.calls == []
    assert events.calls == []


def test_7f_rejection_persists_typed_terminal_event() -> None:
    admission, _eos, _waits, events = _admission(_document_receipt(state="REJECTED"))

    receipt = admission.ingest(_delivery(decision="REJECT"))

    assert receipt["product_resume"]["wait_state"] == "RESUME_QUEUED"
    assert events.calls[0]["authority_state"] == "REJECTED"
    assert events.calls[0]["authority_evidence_ref"] == (
        f"eos.scoped-approval-decision:{DECISION_ID}"
    )


def test_7f_generic_business_receipt_remains_outside_product_resume() -> None:
    generic = {
        "schema_version": "eos_approval_decision_receipt.v1",
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "approval_instance_id": "71000000-0000-4000-8000-000000000009",
        "transition_state": "APPROVED",
    }
    admission, _eos, waits, events = _admission(generic)

    assert admission.ingest(_delivery()) == generic
    assert waits.calls == []
    assert events.calls == []


def test_7f_fails_closed_for_missing_or_drifted_product_wait() -> None:
    missing, *_ = _admission(_document_receipt(), context=None)
    missing._wait_contexts.context = None
    with pytest.raises(ApprovalDecisionEventError, match="No Product wait"):
        missing.ingest(_delivery())

    drifted_context = _wait_context()
    drifted_context["product_binding"]["authority_ref"] = "another-case"
    drifted, *_ = _admission(_document_receipt(), context=drifted_context)
    with pytest.raises(ApprovalDecisionEventError, match="differs"):
        drifted.ingest(_delivery())


def test_7f_fails_closed_without_active_product_event_admission() -> None:
    eos = _EosClient(_document_receipt())
    admission = EosProductApprovalReceiptAdmission(
        eos_client=eos,
        wait_contexts=_Waits(_wait_context()),
        product_events=None,
    )
    with pytest.raises(ApprovalDecisionEventError, match="unavailable") as exc:
        admission.ingest(_delivery())
    assert exc.value.retryable is True


def test_7f_rejects_receipt_lineage_and_evidence_drift() -> None:
    receipt = _document_receipt()
    receipt["case_id"] = "71000000-0000-4000-8000-000000000099"
    admission, *_ = _admission(receipt)
    with pytest.raises(ApprovalDecisionEventError, match="binding differs"):
        admission.ingest(_delivery())

    receipt = _document_receipt()
    receipt["approved_document_envelope"] = None
    admission, *_ = _admission(receipt)
    with pytest.raises(ApprovalDecisionEventError, match="must be an object"):
        admission.ingest(_delivery())

    receipt = _document_receipt()
    receipt["approved_document_envelope"] = {
        "envelope_id": f"eos.scoped-approval-case:{CASE_ID}"
    }
    admission, *_ = _admission(receipt)
    with pytest.raises(
        ApprovalDecisionEventError, match="ApprovedDocument envelope reference"
    ):
        admission.ingest(_delivery())

    receipt = _document_receipt()
    receipt["approved_document_envelope"] = {
        "envelope_id": "71000000000040008000000000000007"
    }
    admission, *_ = _admission(receipt)
    with pytest.raises(ApprovalDecisionEventError, match="not canonical"):
        admission.ingest(_delivery())


def test_7f_terminal_execution_transition_is_idempotent_and_fail_closed() -> None:
    class Executions:
        def __init__(self) -> None:
            self.calls = []

        def transition(self, **values):
            self.calls.append(values)
            return {**values, "version": values["expected_version"] + 1}

    executions = Executions()
    source = object.__new__(SqlAlchemyProductPlanningLineageSource)
    source._executions = executions
    route = SimpleNamespace(tenant_id=TENANT, execution_id=CHECKPOINT_ID)
    waiting = {"state": "WAITING_APPROVAL", "version": 4}

    cancelled = source.close_terminal_execution(
        route=route,
        execution=waiting,
        terminal_stage="PREPARATION_CANCELLED",
    )
    replay = source.close_terminal_execution(
        route=route,
        execution={"state": "CANCELLED", "version": 5},
        terminal_stage="PREPARATION_CANCELLED",
    )

    assert cancelled["state"] == "CANCELLED"
    assert executions.calls[0]["phase"] == "PLAN_BUILD"
    assert replay == {"state": "CANCELLED", "version": 5}
    assert len(executions.calls) == 1
    with pytest.raises(ProductPlanningRuntimeError, match="not waiting for approval"):
        source.close_terminal_execution(
            route=route,
            execution={"state": "RUNNING", "version": 5},
            terminal_stage="PREPARATION_FAILED",
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"base_url": "", "service_token": "token"}, "base URL"),
        ({"base_url": "http://eos", "service_token": ""}, "service token"),
        (
            {
                "base_url": "http://eos",
                "service_token": "token",
                "timeout_seconds": True,
            },
            "timeout",
        ),
        (
            {
                "base_url": "http://eos",
                "service_token": "token",
                "timeout_seconds": 121,
            },
            "timeout",
        ),
    ],
)
def test_7f_eos_client_configuration_fails_closed(arguments, message) -> None:
    with pytest.raises(ApprovalDecisionEventError, match=message):
        HttpEosBusinessApprovalDecisionClient(**arguments)

    client = HttpEosBusinessApprovalDecisionClient(
        base_url="http://eos/",
        service_token="token",
        timeout_seconds=120,
    )
    assert client._url == "http://eos/internal/v1/approval-decision-events"


def test_7f_eos_client_preserves_bounded_source_problem_code() -> None:
    def opener(request, **_kwargs):
        body = BytesIO(
            json.dumps(
                {
                    "error_code": "eos.document_signoff_context_missing",
                    "detail": "protected domain detail",
                }
            ).encode()
        )
        raise HTTPError(request.full_url, 409, "conflict", {}, body)

    client = HttpEosBusinessApprovalDecisionClient(
        base_url="http://eos",
        service_token="token",
        opener=opener,
    )
    with pytest.raises(ApprovalDecisionEventError) as caught:
        client.ingest(_delivery())
    assert caught.value.error_code == "ae.business_approval_delivery_failed"
    assert "eos.document_signoff_context_missing" in caught.value.detail
    assert "protected domain detail" not in caught.value.detail


def test_7f_typed_receipt_schema_and_state_admission() -> None:
    generic = {
        "schema_version": "eos_approval_decision_receipt.v1",
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "BUSINESS_FORMAL",
        "approval_instance_id": CASE_ID,
        "transition_state": "APPROVED",
    }
    assert approval_api._eos_approval_receipt(generic) == generic
    assert approval_api._eos_approval_receipt(_document_receipt())["purpose"] == (
        "DOCUMENT_SIGNOFF"
    )
    assert approval_api._eos_approval_receipt(_accounting_receipt())["purpose"] == (
        "ACCOUNTING_POSTING"
    )

    invalid_values = [
        ({**generic, "schema_version": "unknown"}, "unsupported"),
        ({**generic, "transition_state": "BROKEN"}, "transition state"),
        ({**generic, "approval_instance_id": ""}, "approval_instance_id"),
        ({**_document_receipt(), "purpose": "ACCOUNTING_POSTING"}, "purpose"),
        ({**_document_receipt(), "case_id": ""}, "case_id"),
        ({**_document_receipt(), "case_state": "BROKEN"}, "state"),
        ({**_document_receipt(), "approval_domain": "NSL_WRITE"}, "domain"),
    ]
    for value, message in invalid_values:
        with pytest.raises(ApprovalDecisionEventError, match=message):
            approval_api._eos_approval_receipt(value)


def test_7f_authority_receipt_terminal_drift_matrix() -> None:
    delivery = _delivery()
    work_item = delivery["work_item"]
    decision = delivery["decision"]
    event = delivery["event"]
    variants = [
        (
            _document_receipt(),
            {**decision, "decision": "REJECT"},
            event,
            "decision differs",
        ),
        (
            {**_document_receipt(state="REJECTED"), "approved_document_envelope": {}},
            {**decision, "decision": "REJECT"},
            event,
            "contains approval evidence",
        ),
        (
            {**_document_receipt(state="PENDING"), "approved_document_envelope": {}},
            decision,
            event,
            "contains terminal evidence",
        ),
        (
            _document_receipt(),
            decision,
            {**event, "occurred_at": "2026-11-19T01:02:04Z"},
            "event time differs",
        ),
    ]
    for receipt, admitted_decision, admitted_event, message in variants:
        with pytest.raises(ApprovalDecisionEventError, match=message):
            approval_api._product_authority_receipt(
                receipt,
                work_item=work_item,
                decision=admitted_decision,
                event=admitted_event,
            )


def test_7f_product_resume_error_preserves_or_normalizes_failure_contract() -> None:
    existing = ApprovalDecisionEventError("existing", "existing detail")
    assert approval_api._product_resume_error(existing) is existing

    domain = SimpleNamespace(
        error_code="domain.conflict",
        detail="domain detail",
        retryable=False,
    )
    admitted = approval_api._product_resume_error(domain)
    assert (admitted.error_code, admitted.status_code, admitted.retryable) == (
        "domain.conflict",
        409,
        False,
    )

    unavailable = approval_api._product_resume_error(RuntimeError("secret"))
    assert unavailable.error_code == "ae.product_approval_resume_failed"
    assert unavailable.status_code == 503
    assert unavailable.retryable is True
    assert "secret" not in unavailable.detail


def test_7f_delivery_lineage_and_datetime_validation() -> None:
    delivery = _delivery()
    delivery["work_item"]["tenant_id"] = "OTHER"
    with pytest.raises(ApprovalDecisionEventError, match="work-item lineage"):
        approval_api._delivery(delivery)

    delivery = _delivery()
    delivery["decision"]["decision_id"] = "other-decision"
    with pytest.raises(ApprovalDecisionEventError, match="decision lineage"):
        approval_api._delivery(delivery)

    with pytest.raises(ApprovalDecisionEventError, match="invalid"):
        approval_api._datetime("not-a-time")
    with pytest.raises(ApprovalDecisionEventError, match="timezone"):
        approval_api._datetime("2026-11-19T01:02:03")
