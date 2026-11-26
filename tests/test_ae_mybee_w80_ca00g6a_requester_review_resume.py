from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from nex_ae_api.product_planning_runtime import (
    InstalledProductRequesterReviewAdmission,
    ProductPlanningRuntimeError,
)
from nex_ae_api.product_preparation_persistence import (
    ProductPreparationPersistenceError,
    seal_product_preparation_event,
    seal_product_preparation_wait_binding,
)

TENANT = "VO00"
REQUESTER = "employee-8101"
CHECKPOINT_ID = "81000000-0000-4000-8000-000000000001"
EXECUTION_ID = "81000000-0000-4000-8000-000000000002"
WORK_INTENT_ID = "81000000-0000-4000-8000-000000000003"
WAIT_ID = "81000000-0000-4000-8000-000000000004"
HASH = "sha256:" + "8" * 64
NOW = datetime(2026, 11, 26, 1, 2, 3, tzinfo=UTC)


class _WaitEvents:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def resolve_product_wait_context(self, **values):
        self.calls.append(values)
        return copy.deepcopy(self.context)


class _Coordinator:
    def __init__(self) -> None:
        self.calls = []
        self.event_ids = set()

    def accept_approval_notification(self, **values):
        self.calls.append(values)
        replayed = values["event_id"] in self.event_ids
        self.event_ids.add(values["event_id"])
        return {"replayed": replayed}


class _Runtimes:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.calls = []

    def resolve_identity(self, **values):
        self.calls.append(values)
        return SimpleNamespace(coordinator=self.coordinator)


class _Resume:
    def __init__(self) -> None:
        self.calls = []

    def reconcile(self, **values):
        self.calls.append(values)
        return {
            "event_state": "MATCHED",
            "wait_state": "RESUME_QUEUED",
            "resume_runtime_job_id": "resume-job-6a",
        }


def _context(*, requester_ref=REQUESTER, authority_kind="REQUESTER_PROPOSAL_REVIEW"):
    return {
        "wait": {"state": "PENDING"},
        "product_binding": {
            "coordinator_id": "mybee.finance.transaction-preparation",
            "coordinator_version": "1.2.0",
            "coordinator_registration_hash": HASH,
            "authority_kind": authority_kind,
        },
        "checkpoint": {
            "checkpoint_id": CHECKPOINT_ID,
            "requester_ref": requester_ref,
        },
    }


def _admission(context):
    coordinator = _Coordinator()
    waits = _WaitEvents(context)
    resume = _Resume()
    admission = InstalledProductRequesterReviewAdmission(
        runtimes=_Runtimes(coordinator),
        wait_events=waits,
        resume_service=resume,
        clock=lambda: NOW,
    )
    return admission, coordinator, waits, resume


def test_requester_review_admission_ignores_unrelated_manual_document() -> None:
    admission, coordinator, waits, resume = _admission(None)

    receipt = admission.ingest(
        tenant_id=TENANT,
        requester_ref=REQUESTER,
        authority_kind="REQUESTER_PROPOSAL_REVIEW",
        authority_ref="eos.business-proposal:manual-proposal",
        receipt={"state": "SUBMITTED"},
    )

    assert receipt["matched"] is False
    assert waits.calls[0]["tenant_id"] == TENANT
    assert coordinator.calls == []
    assert resume.calls == []


def test_requester_review_admission_rejects_owner_and_kind_drift() -> None:
    admission, _coordinator, _waits, _resume = _admission(
        _context(requester_ref="employee-other")
    )
    with pytest.raises(ProductPlanningRuntimeError) as owner:
        admission.ingest(
            tenant_id=TENANT,
            requester_ref=REQUESTER,
            authority_kind="REQUESTER_PROPOSAL_REVIEW",
            authority_ref="eos.business-proposal:proposal-6a",
            receipt={"state": "SUBMITTED"},
        )
    assert owner.value.error_code == "ae.product_planning_runtime_conflict"

    with pytest.raises(ProductPlanningRuntimeError) as kind:
        admission.ingest(
            tenant_id=TENANT,
            requester_ref=REQUESTER,
            authority_kind="BUSINESS_FORMAL",
            authority_ref="case-6a",
            receipt={"state": "APPROVED"},
        )
    assert kind.value.error_code == "ae.product_planning_runtime_invalid"


def test_requester_review_admission_is_domain_bound_and_ack_loss_safe() -> None:
    admission, coordinator, _waits, resume = _admission(_context())
    values = {
        "tenant_id": TENANT,
        "requester_ref": REQUESTER,
        "authority_kind": "REQUESTER_PROPOSAL_REVIEW",
        "authority_ref": "eos.business-proposal:proposal-6a",
        "receipt": {
            "schema_version": "eos.business_proposal.v1",
            "tenant_id": TENANT,
            "proposal_id": "proposal-6a",
            "state": "SUBMITTED",
        },
    }

    first = admission.ingest(**values)
    replay = admission.ingest(**values)

    assert first["matched"] is True
    assert replay["event_id"] == first["event_id"]
    assert replay["receipt_hash"] == first["receipt_hash"]
    assert first["event_replayed"] is False
    assert replay["event_replayed"] is True
    assert coordinator.calls[0] == coordinator.calls[1]
    assert coordinator.calls[0]["received_at"] == "2026-11-26T01:02:03Z"
    assert resume.calls == [
        {"tenant_id": TENANT, "event_id": first["event_id"]},
        {"tenant_id": TENANT, "event_id": first["event_id"]},
    ]


@pytest.mark.parametrize(
    ("authority_kind", "event_type"),
    [
        ("REQUESTER_PROPOSAL_REVIEW", "PROPOSAL_REVIEW_SUBMITTED"),
        ("REQUESTER_VOUCHER_REVIEW", "VOUCHER_REVIEW_SUBMITTED"),
    ],
)
def test_requester_review_wait_and_event_contracts_are_admitted(
    authority_kind, event_type
) -> None:
    binding = seal_product_preparation_wait_binding(
        {
            "tenant_id": TENANT,
            "wait_id": WAIT_ID,
            "checkpoint_id": CHECKPOINT_ID,
            "checkpoint_hash": HASH,
            "coordinator_id": "mybee.finance.transaction-preparation",
            "coordinator_version": "1.2.0",
            "coordinator_registration_hash": HASH,
            "expected_event_type": event_type,
            "authority_kind": authority_kind,
            "authority_ref": "eos.review:6a",
            "agent_execution_id": EXECUTION_ID,
            "work_intent_id": WORK_INTENT_ID,
            "created_at": "2026-11-26T01:02:03Z",
        }
    )
    event = seal_product_preparation_event(
        {
            "tenant_id": TENANT,
            "event_id": f"event-{event_type.lower()}",
            "event_type": event_type,
            "external_ref": "eos.review:6a",
            "event_payload": {"authority_state": "APPROVED"},
            "received_at": "2026-11-26T01:02:03Z",
        }
    )

    assert binding["authority_kind"] == authority_kind
    assert event["event_type"] == event_type
    invalid_binding = {
        key: value for key, value in binding.items() if key != "binding_hash"
    }
    with pytest.raises(ProductPreparationPersistenceError):
        seal_product_preparation_wait_binding(
            {**invalid_binding, "authority_kind": "ACCOUNTING_REVIEW"}
        )
