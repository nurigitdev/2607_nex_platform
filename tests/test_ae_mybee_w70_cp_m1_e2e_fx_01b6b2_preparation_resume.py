from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.m1_product_preparation_coordinator as coordinator_module
import pytest
from mybee_ax.orchestration import (
    M1PreparationAuthority,
    load_m1_transaction_preparation_registration,
)
from nex_ae_api.m1_product_planning_coordinator import (
    M1_PRODUCT_PLANNING_POLICY,
    build_m1_product_planning_coordinator_registration,
)
from nex_ae_api.m1_product_preparation_coordinator import (
    InstalledM1ProductPlanningCoordinator,
    M1ProductPreparationCoordinatorError,
    m1_product_planning_fallback_ref,
    m1_product_planning_proposal_ref,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_planning_coordinators import ProductPlanningPolicy
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
SUBJECT = "employee-100"
EXECUTION_ID = "33333333-3333-4333-8333-333333333333"
CONTEXT_ID = "41000000-0000-4000-8000-000000000012"
SNAPSHOT_ID = "41000000-0000-4000-8000-000000000013"
COMPANY_ID = "41000000-0000-4000-8000-000000000001"
PROJECT_ID = "41000000-0000-4000-8000-000000000002"
DEBIT_ID = "41000000-0000-4000-8000-000000000004"
CREDIT_ID = "41000000-0000-4000-8000-000000000005"
BUSINESS_POLICY_ID = "41000000-0000-4000-8000-000000000006"
ACCOUNTING_POLICY_ID = "41000000-0000-4000-8000-000000000007"
ENVELOPE_ID = "41000000-0000-4000-8000-000000000009"
CANDIDATE_ID = "41000000-0000-4000-8000-000000000010"
EVIDENCE_ID = "41000000-0000-4000-8000-000000000011"
NOW = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)
NOW_TEXT = "2026-11-17T01:00:00Z"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
DETERMINISTIC_POLICY = ProductPlanningPolicy(
    mode="DETERMINISTIC_ONLY",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key="ae.plan_builder.project_delegation.v1",
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref=None,
    proposal_consumers=(),
)
OPTIONAL_POLICY = ProductPlanningPolicy(
    mode="PROVIDER_ASSISTED_OPTIONAL",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key="ae.plan_builder.project_delegation.v1",
    admission_policy_ref="ae.product_planning_proposal.strict.v1",
    deterministic_fallback_ref="nex-ae:m1-deterministic-fallback:v1",
    proposal_consumers=("PREPARATION",),
)


class _CheckpointRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def append(self, checkpoint):
        saved = self.records.setdefault(checkpoint["checkpoint_id"], dict(checkpoint))
        if saved["checkpoint_hash"] != checkpoint["checkpoint_hash"]:
            raise AssertionError("checkpoint replay drift")
        return copy.deepcopy(saved)

    def get(self, *, tenant_id, checkpoint_id):
        value = self.records.get(checkpoint_id)
        return (
            copy.deepcopy(value)
            if value is not None and value["tenant_id"] == tenant_id
            else None
        )

    def latest(
        self, *, tenant_id, agent_execution_id, coordinator_id, coordinator_version
    ):
        matches = [
            item
            for item in self.records.values()
            if (
                item["tenant_id"],
                item["agent_execution_id"],
                item["coordinator_id"],
                item["coordinator_version"],
            )
            == (
                tenant_id,
                agent_execution_id,
                coordinator_id,
                coordinator_version,
            )
        ]
        return (
            None
            if not matches
            else copy.deepcopy(
                max(matches, key=lambda item: item["checkpoint_version"])
            )
        )


class _WaitEventRepository:
    def __init__(self, checkpoints: _CheckpointRepository) -> None:
        self.checkpoints = checkpoints
        self.waits: dict[str, dict] = {}
        self.wait_bindings: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.event_bindings: dict[str, dict] = {}

    def register_wait(self, wait, *, product_binding=None):
        saved = self.waits.setdefault(
            wait["wait_id"],
            {
                **dict(wait),
                "state": "PENDING",
                "matched_event_id": None,
                "resume_runtime_job_id": None,
            },
        )
        binding = self.wait_bindings.setdefault(wait["wait_id"], dict(product_binding))
        return {
            "wait": copy.deepcopy(saved),
            "product_binding": copy.deepcopy(binding),
        }

    def load_product_wait_context(self, *, tenant_id, wait_id):
        wait = self.waits.get(wait_id)
        binding = self.wait_bindings.get(wait_id)
        if wait is None or binding is None or wait["tenant_id"] != tenant_id:
            return None
        checkpoint = self.checkpoints.get(
            tenant_id=tenant_id, checkpoint_id=binding["checkpoint_id"]
        )
        return {
            "wait": copy.deepcopy(wait),
            "product_binding": copy.deepcopy(binding),
            "checkpoint": checkpoint,
        }

    def accept_event(self, event, *, product_binding=None):
        previous = self.events.setdefault(
            event["event_id"], {**dict(event), "state": "RECEIVED"}
        )
        if previous["event_semantic_hash"] != event["event_semantic_hash"]:
            raise AssertionError("event replay drift")
        binding = self.event_bindings.setdefault(
            event["event_id"], dict(product_binding)
        )
        return {
            "event": copy.deepcopy(previous),
            "product_binding": copy.deepcopy(binding),
        }

    def load_product_event_context(self, *, tenant_id, event_id):
        event = self.events.get(event_id)
        event_binding = self.event_bindings.get(event_id)
        if event is None or event_binding is None or event["tenant_id"] != tenant_id:
            return None
        wait = self.waits[event_binding["wait_id"]]
        wait_binding = self.wait_bindings[event_binding["wait_id"]]
        checkpoint = self.checkpoints.get(
            tenant_id=tenant_id, checkpoint_id=event_binding["checkpoint_id"]
        )
        return {
            "event": copy.deepcopy(event),
            "event_binding": copy.deepcopy(event_binding),
            "wait": copy.deepcopy(wait),
            "wait_binding": copy.deepcopy(wait_binding),
            "checkpoint": checkpoint,
        }


class _AuthoritySource:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str | None] = []
        self.fail = fail

    def resolve(self, *, checkpoint, **_values):
        self.calls.append(None if checkpoint is None else checkpoint["stage"])
        if self.fail:
            raise ConnectionError("authority unavailable")
        return _authority()


class _PreparationAdapter:
    def __init__(self) -> None:
        self.registration = load_m1_transaction_preparation_registration()
        self.calls: list[tuple[str, str | None]] = []

    def begin_proposal(self, **values):
        self.calls.append(("BEGIN", None))
        return _preparation(
            "WAITING_BUSINESS_APPROVAL",
            values["business_context_hash"],
            {"business_approval_case_id": "business-case-100"},
        )

    def continue_after_business_approval(self, **values):
        self.calls.append(("BUSINESS", values["envelope_id"]))
        return _preparation(
            "WAITING_ACCOUNTING_APPROVAL",
            values["business_context_hash"],
            {
                "approved_document_envelope_id": values["envelope_id"],
                "business_approval_proof_id": "business-proof-100",
                "candidate_id": CANDIDATE_ID,
                "candidate_version": 1,
                "candidate_revision": 1,
                "candidate_hash": HASH_A,
                "validation_hash": HASH_B,
                "accounting_approval_case_id": "accounting-case-100",
            },
        )

    def continue_after_accounting_approval(self, **values):
        self.calls.append(("ACCOUNTING", values["accounting_approval_evidence_id"]))
        assert values["candidate_id"] == CANDIDATE_ID
        return _preparation(
            "READY_FOR_D04",
            values["business_context_hash"],
            {
                "candidate_id": CANDIDATE_ID,
                "candidate_version": 2,
                "candidate_revision": 1,
                "candidate_hash": HASH_A,
                "accounting_approval_evidence_id": values[
                    "accounting_approval_evidence_id"
                ],
                "accounting_proof_hash": HASH_B,
                "posting_admission_id": "posting-admission-100",
                "posting_admission_hash": HASH_C,
                "posting_admission_expires_at": "2026-11-17T01:05:00Z",
            },
        )


class _ReviewPreparationAdapter(_PreparationAdapter):
    def begin_proposal(self, **values):
        self.calls.append(("PROPOSAL_DRAFT", None))
        return _preparation(
            "WAITING_PROPOSAL_REVIEW",
            values["business_context_hash"],
            {"proposal_review_ref": "eos.business-proposal:proposal-100"},
        )

    def continue_after_proposal_review(self, **values):
        self.calls.append(("PROPOSAL_SUBMIT", None))
        return _preparation(
            "WAITING_BUSINESS_APPROVAL",
            values["business_context_hash"],
            {"business_approval_case_id": "business-case-100"},
        )

    def continue_after_business_approval(self, **values):
        self.calls.append(("BUSINESS", values["envelope_id"]))
        return _preparation(
            "WAITING_VOUCHER_REVIEW",
            values["business_context_hash"],
            {
                "candidate_id": CANDIDATE_ID,
                "voucher_review_ref": f"eos.voucher-candidate:{CANDIDATE_ID}",
            },
        )

    def continue_after_voucher_review(self, **values):
        self.calls.append(("VOUCHER_SUBMIT", values["candidate_id"]))
        return _preparation(
            "WAITING_ACCOUNTING_APPROVAL",
            values["business_context_hash"],
            {
                "candidate_id": values["candidate_id"],
                "accounting_approval_case_id": "accounting-case-100",
            },
        )


def _preparation(stage: str, context_hash: str, references: dict) -> dict:
    value = {
        "schema_version": "nex.mybee.m1-transaction-preparation.v1",
        "stage": stage,
        "business_context_hash": context_hash,
        "authority_hash": HASH_A,
        "authority": {"authority_hash": HASH_A},
        "adapter_identity": load_m1_transaction_preparation_registration().source_identity,
        "identities": {"proposal_id": "proposal-100"},
        "references": references,
    }
    value["preparation_hash"] = semantic_sha256_hash_ref(value)
    return value


def _authority() -> M1PreparationAuthority:
    return M1PreparationAuthority(
        tenant_id=TENANT,
        requester_subject_id=SUBJECT,
        company_id=COMPANY_ID,
        company_code="NURIVOICE",
        company_selector_kind="CODE_OR_NAME",
        company_selector_value="NURIVOICE",
        company_version=3,
        company_evidence_hash=HASH_A,
        functional_currency="KRW",
        primary_project_id=PROJECT_ID,
        primary_project_code="VO00D260101",
        project_refs=(
            {
                "project_id": PROJECT_ID,
                "project_code": "VO00D260101",
                "project_version": 7,
            },
        ),
        project_authorizations=(
            {
                "project_code": "VO00D260101",
                "decision_ref": "oa.authorization:m1-project",
                "revision_hash": HASH_A,
                "source_version": 7,
            },
        ),
        debit_account_id=DEBIT_ID,
        debit_semantic_key="MB-COA-OTHER-EXPENSE",
        debit_account_evidence_hash=HASH_A,
        credit_account_id=CREDIT_ID,
        credit_semantic_key="MB-COA-ACCOUNTS-PAYABLE-FX",
        credit_account_evidence_hash=HASH_B,
        business_approval_policy_id=BUSINESS_POLICY_ID,
        business_approval_policy_version=3,
        business_approval_policy_hash=HASH_A,
        accounting_approval_policy_id=ACCOUNTING_POLICY_ID,
        accounting_approval_policy_version=2,
        accounting_approval_policy_hash=HASH_B,
        project_authorization_ref="oa.authorization:m1-project-set",
        project_authorization_revision_hash=HASH_C,
        authority_effective_at=NOW,
    )


def _inputs():
    work_intent = json.loads(
        (
            ROOT
            / "contracts/examples/service/ae_work_intent.business_transaction.v1_2.json"
        ).read_text(encoding="utf-8")
    )
    context = {
        "context_id": CONTEXT_ID,
        "context_generation": 1,
        "execution_id": EXECUTION_ID,
        "identity": {"tenant_id": TENANT, "subject_id": SUBJECT},
    }
    context["context_hash"] = semantic_sha256_hash_ref(context)
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            )
        }
    )
    snapshot = build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT_ID,
        snapshot_version=1,
        created_at=NOW_TEXT,
        capabilities=tuple(item.capability for item in capabilities.registrations),
    )
    return work_intent, context, snapshot, {"execution_id": EXECUTION_ID}


def _coordinator(
    *,
    authority_source=None,
    planning_policy=DETERMINISTIC_POLICY,
    adapter=None,
):
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v4.json"
            )
        }
    )
    selected_adapter = adapter or _PreparationAdapter()
    registration = build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=selected_adapter.registration,
        planning_policy=planning_policy,
    )
    checkpoints = _CheckpointRepository()
    waits = _WaitEventRepository(checkpoints)
    source = authority_source or _AuthoritySource()
    coordinator = InstalledM1ProductPlanningCoordinator(
        registration=registration,
        transaction_preparation=SimpleNamespace(adapter=selected_adapter),
        authority_source=source,
        checkpoints=checkpoints,
        wait_events=waits,
        clock=lambda: NOW,
    )
    return coordinator, selected_adapter, source, checkpoints, waits


def _planning_proposal(registration, work_intent, context):
    proposal = {
        "schema_version": "ae.product_planning_proposal.v1",
        "tenant_id": TENANT,
        "owner_subject_id": SUBJECT,
        "execution_id": work_intent["execution_id"],
        "work_intent_ref": {
            "work_intent_id": work_intent["work_intent_id"],
            "intent_hash": work_intent["intent_hash"],
        },
        "agent_context_ref": {
            "context_id": context["context_id"],
            "context_hash": context["context_hash"],
        },
        "coordinator_ref": {
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "coordinator_registration_hash": registration.registration_hash,
        },
        "planning_policy": registration.planning_policy.projection(),
        "candidate_ref": {
            "candidate_id": "42000000-0000-4000-8000-000000000001",
            "candidate_hash": HASH_A,
            "storage_ref": "private://semantic-candidates/plan-1",
            "size_bytes": 128,
        },
        "suggested_capability_ids": [registration.capability_id],
        "provider_provenance": {
            "model_ref": "Qwen3.5-9B",
            "admission_policy_ref": "semantic-admission://plan/revision-1",
        },
        "created_at": NOW_TEXT,
        "content_included": False,
        "provider_plan_authoritative": False,
    }
    proposal["proposal_hash"] = semantic_sha256_hash_ref(proposal)
    return proposal


def _notify(
    coordinator, checkpoint, *, event_id, evidence_ref, authority_state="APPROVED"
):
    return coordinator.accept_approval_notification(
        tenant_id=TENANT,
        checkpoint_id=checkpoint["checkpoint_id"],
        event_id=event_id,
        notification_ref=f"wc-event://{event_id}",
        authority_evidence_ref=evidence_ref,
        received_at=NOW_TEXT,
        authority_state=authority_state,
    )


def _match(waits: _WaitEventRepository, *, event_id: str) -> str:
    event_binding = waits.event_bindings[event_id]
    wait = waits.waits[event_binding["wait_id"]]
    runtime_job_id = "41000000-0000-4000-8000-000000000070"
    wait.update(
        state="RESUME_QUEUED",
        matched_event_id=event_id,
        resume_runtime_job_id=runtime_job_id,
    )
    waits.events[event_id]["state"] = "MATCHED"
    return runtime_job_id


def test_6b2_reaches_ready_through_two_fresh_authority_resumes() -> None:
    coordinator, adapter, source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()

    business = coordinator.begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )
    assert business["checkpoint"]["stage"] == "WAITING_BUSINESS_APPROVAL"
    assert business["wait"]["product_binding"]["authority_kind"] == "BUSINESS_FORMAL"
    _notify(
        coordinator,
        business["checkpoint"],
        event_id="business-approved-100",
        evidence_ref=ENVELOPE_ID,
    )
    business_job_id = _match(waits, event_id="business-approved-100")
    accounting = coordinator.resume_approval(
        event_id="business-approved-100",
        runtime_job_id=business_job_id,
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )
    assert accounting["checkpoint"]["stage"] == "WAITING_ACCOUNTING_APPROVAL"
    assert accounting["wait"]["product_binding"]["authority_kind"] == (
        "ACCOUNTING_REVIEW"
    )
    _notify(
        coordinator,
        accounting["checkpoint"],
        event_id="accounting-approved-100",
        evidence_ref=EVIDENCE_ID,
    )
    accounting_job_id = _match(waits, event_id="accounting-approved-100")
    ready = coordinator.resume_approval(
        event_id="accounting-approved-100",
        runtime_job_id=accounting_job_id,
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )

    assert ready["ready"] is True
    assert ready["wait"] is None
    assert ready["checkpoint"]["stage"] == "READY_FOR_D04"
    assert ready["checkpoint"]["checkpoint_version"] == 3
    assert len(checkpoints.records) == 3
    assert len(waits.waits) == 2
    assert source.calls == [
        None,
        "WAITING_BUSINESS_APPROVAL",
        "WAITING_ACCOUNTING_APPROVAL",
    ]
    assert adapter.calls == [
        ("BEGIN", None),
        ("BUSINESS", ENVELOPE_ID),
        ("ACCOUNTING", EVIDENCE_ID),
    ]


def test_6a_review_aware_coordinator_stops_and_resumes_at_four_boundaries() -> None:
    coordinator, adapter, source, checkpoints, waits = _coordinator(
        adapter=_ReviewPreparationAdapter()
    )
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    current = coordinator.begin(**values)
    assert current["checkpoint"]["stage"] == "WAITING_PROPOSAL_REVIEW"

    transitions = (
        (
            "proposal-submitted-6a",
            "eos.business-proposal:proposal-100",
            "WAITING_BUSINESS_APPROVAL",
        ),
        ("business-approved-6a", ENVELOPE_ID, "WAITING_VOUCHER_REVIEW"),
        (
            "voucher-submitted-6a",
            f"eos.voucher-candidate:{CANDIDATE_ID}",
            "WAITING_ACCOUNTING_APPROVAL",
        ),
        ("accounting-approved-6a", EVIDENCE_ID, "READY_FOR_D04"),
    )
    for event_id, evidence_ref, expected_stage in transitions:
        _notify(
            coordinator,
            current["checkpoint"],
            event_id=event_id,
            evidence_ref=evidence_ref,
        )
        runtime_job_id = _match(waits, event_id=event_id)
        current = coordinator.resume_approval(
            event_id=event_id,
            runtime_job_id=runtime_job_id,
            **values,
        )
        assert current["checkpoint"]["stage"] == expected_stage

    assert current["ready"] is True
    assert current["checkpoint"]["checkpoint_version"] == 5
    assert len(checkpoints.records) == 5
    assert len(waits.waits) == 4
    assert source.calls == [
        None,
        "WAITING_PROPOSAL_REVIEW",
        "WAITING_BUSINESS_APPROVAL",
        "WAITING_VOUCHER_REVIEW",
        "WAITING_ACCOUNTING_APPROVAL",
    ]
    assert adapter.calls == [
        ("PROPOSAL_DRAFT", None),
        ("PROPOSAL_SUBMIT", None),
        ("BUSINESS", ENVELOPE_ID),
        ("VOUCHER_SUBMIT", CANDIDATE_ID),
        ("ACCOUNTING", EVIDENCE_ID),
    ]


def test_6a_requester_review_wait_rejects_rejected_authority_state() -> None:
    coordinator, adapter, _source, checkpoints, waits = _coordinator(
        adapter=_ReviewPreparationAdapter()
    )
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    waiting = coordinator.begin(**values)
    _notify(
        coordinator,
        waiting["checkpoint"],
        event_id="proposal-review-rejected-6a",
        evidence_ref="eos.business-proposal:proposal-100",
        authority_state="REJECTED",
    )
    runtime_job_id = _match(waits, event_id="proposal-review-rejected-6a")

    with pytest.raises(
        M1ProductPreparationCoordinatorError,
        match="Requester review submission cannot be rejected",
    ):
        coordinator.resume_approval(
            event_id="proposal-review-rejected-6a",
            runtime_job_id=runtime_job_id,
            **values,
        )

    assert len(checkpoints.records) == 1
    assert adapter.calls == [("PROPOSAL_DRAFT", None)]


def test_business_resume_requires_canonical_approved_document_envelope_ref() -> None:
    coordinator, adapter, _source, _checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    waiting = coordinator.begin(**values)
    _notify(
        coordinator,
        waiting["checkpoint"],
        event_id="business-invalid-envelope-100",
        evidence_ref=f"eos.scoped-approval-case:{BUSINESS_POLICY_ID}",
    )
    runtime_job_id = _match(waits, event_id="business-invalid-envelope-100")

    with pytest.raises(
        M1ProductPreparationCoordinatorError,
        match="approved_document_envelope_id is invalid",
    ):
        coordinator.resume_approval(
            event_id="business-invalid-envelope-100",
            runtime_job_id=runtime_job_id,
            **values,
        )

    assert adapter.calls == [("BEGIN", None)]


@pytest.mark.parametrize(
    ("value", "message"),
    (
        ("x" * 36, "is invalid"),
        ("41000000000040008000000000000009", "is not canonical"),
        ("AAAAAAAA-0000-4000-8000-000000000009", "is not canonical"),
    ),
)
def test_approved_document_envelope_ref_rejects_malformed_or_compact_uuid(
    value: str, message: str
) -> None:
    with pytest.raises(M1ProductPreparationCoordinatorError, match=message):
        coordinator_module._approved_document_envelope_ref(value)


def test_7f_rejected_authority_creates_terminal_checkpoint_without_mutation() -> None:
    coordinator, adapter, source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    waiting = coordinator.begin(**values)
    _notify(
        coordinator,
        waiting["checkpoint"],
        event_id="business-rejected-100",
        evidence_ref="eos.scoped-approval-decision:decision-100",
        authority_state="REJECTED",
    )
    runtime_job_id = _match(waits, event_id="business-rejected-100")

    terminal = coordinator.resume_approval(
        event_id="business-rejected-100",
        runtime_job_id=runtime_job_id,
        **values,
    )
    replay = coordinator.resume_approval(
        event_id="business-rejected-100",
        runtime_job_id=runtime_job_id,
        **values,
    )

    assert terminal["ready"] is False
    assert terminal["terminal"] is True
    assert terminal["wait"] is None
    assert terminal["checkpoint"]["stage"] == "PREPARATION_CANCELLED"
    assert terminal["checkpoint"]["stage_kind"] == "TERMINAL"
    assert replay["replayed"] is True
    assert replay["checkpoint"] == terminal["checkpoint"]
    assert len(checkpoints.records) == 2
    assert source.calls == [None]
    assert adapter.calls == [("BEGIN", None)]


def test_required_product_proposal_is_bounded_and_replayed_exactly() -> None:
    coordinator, adapter, _source, checkpoints, _waits = _coordinator(
        planning_policy=M1_PRODUCT_PLANNING_POLICY
    )
    work_intent, context, snapshot, execution = _inputs()
    proposal = _planning_proposal(coordinator.registration, work_intent, context)
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
        "planning_proposal": proposal,
    }

    first = coordinator.begin(**values)
    replay = coordinator.begin(**values)

    assert replay["replayed"] is True
    assert replay["checkpoint"] == first["checkpoint"]
    proposal_records = [
        item
        for item in first["checkpoint"]["authority_refs"]
        if item.get("ref_kind") == "PRODUCT_PLANNING_PROPOSAL"
    ]
    assert proposal_records == [
        {
            "ref_kind": "PRODUCT_PLANNING_PROPOSAL",
            "projection": {
                "schema_version": "ae.product_planning_proposal_ref.v1",
                "proposal_hash": proposal["proposal_hash"],
                "candidate_id": proposal["candidate_ref"]["candidate_id"],
                "candidate_hash": proposal["candidate_ref"]["candidate_hash"],
                "candidate_payload_storage_ref": proposal["candidate_ref"][
                    "storage_ref"
                ],
            },
        }
    ]
    assert "provider_provenance" not in proposal_records[0]["projection"]
    assert len(checkpoints.records) == 1
    assert adapter.calls == [("BEGIN", None)]

    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        coordinator.begin(**{**values, "planning_fallback_ref": "drifted"})
    assert raised.value.error_code == "ae.m1_product_preparation_invalid"
    assert len(checkpoints.records) == 1
    assert adapter.calls == [("BEGIN", None)]

    drifted = copy.deepcopy(proposal)
    drifted["candidate_ref"]["candidate_id"] = "42000000-0000-4000-8000-000000000002"
    drifted["proposal_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in drifted.items() if key != "proposal_hash"}
    )
    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        coordinator.begin(**{**values, "planning_proposal": drifted})

    assert raised.value.error_code == "ae.m1_product_preparation_conflict"
    assert len(checkpoints.records) == 1
    assert adapter.calls == [("BEGIN", None)]


def test_required_product_rejects_missing_proposal_before_mutation() -> None:
    coordinator, adapter, _source, checkpoints, _waits = _coordinator(
        planning_policy=M1_PRODUCT_PLANNING_POLICY
    )
    work_intent, context, snapshot, execution = _inputs()

    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        coordinator.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )

    assert raised.value.error_code == "ae.m1_product_preparation_invalid"
    assert checkpoints.records == {}
    assert adapter.calls == []


def test_optional_product_fallback_is_bounded_and_replayed_without_recall() -> None:
    coordinator, adapter, _source, checkpoints, _waits = _coordinator(
        planning_policy=OPTIONAL_POLICY
    )
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
        "planning_fallback_ref": OPTIONAL_POLICY.deterministic_fallback_ref,
    }

    first = coordinator.begin(**values)
    replay = coordinator.replay_begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )

    assert replay is not None
    assert replay["replayed"] is True
    assert replay["checkpoint"] == first["checkpoint"]
    assert replay["planning_proposal_ref"] is None
    assert replay["planning_fallback_ref"] == (
        OPTIONAL_POLICY.deterministic_fallback_ref
    )
    fallback_records = [
        item
        for item in first["checkpoint"]["authority_refs"]
        if item.get("ref_kind") == "PRODUCT_PLANNING_FALLBACK"
    ]
    assert fallback_records == [
        {
            "ref_kind": "PRODUCT_PLANNING_FALLBACK",
            "fallback_ref": OPTIONAL_POLICY.deterministic_fallback_ref,
        }
    ]
    assert len(checkpoints.records) == 1
    assert adapter.calls == [("BEGIN", None)]


def test_product_planning_selection_and_replay_fail_closed_before_mutation() -> None:
    deterministic, deterministic_adapter, *_ = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    with pytest.raises(M1ProductPreparationCoordinatorError):
        deterministic.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
            planning_fallback_ref="nex-ae:unadmitted-fallback:v1",
        )

    optional, optional_adapter, _source, checkpoints, _waits = _coordinator(
        planning_policy=OPTIONAL_POLICY
    )
    assert (
        optional.replay_begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )
        is None
    )
    proposal = _planning_proposal(optional.registration, work_intent, context)
    with pytest.raises(M1ProductPreparationCoordinatorError):
        optional.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
            planning_proposal=proposal,
            planning_fallback_ref=OPTIONAL_POLICY.deterministic_fallback_ref,
        )

    first = optional.begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
        planning_fallback_ref=OPTIONAL_POLICY.deterministic_fallback_ref,
    )
    stored = checkpoints.records[first["checkpoint"]["checkpoint_id"]]
    stored["checkpoint_version"] = 2
    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        optional.replay_begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )

    assert raised.value.error_code == "ae.m1_product_preparation_conflict"
    assert deterministic_adapter.calls == []
    assert optional_adapter.calls == [("BEGIN", None)]


def test_product_planning_policy_guards_reject_invalid_proposal_paths() -> None:
    work_intent, context, snapshot, execution = _inputs()
    deterministic, deterministic_adapter, *_ = _coordinator()
    deterministic_proposal = _planning_proposal(
        deterministic.registration, work_intent, context
    )
    with pytest.raises(M1ProductPreparationCoordinatorError):
        deterministic.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
            planning_proposal=deterministic_proposal,
        )

    optional, optional_adapter, *_ = _coordinator(planning_policy=OPTIONAL_POLICY)
    with pytest.raises(M1ProductPreparationCoordinatorError):
        optional.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
            planning_proposal={"schema_version": "invalid"},
        )
    with pytest.raises(M1ProductPreparationCoordinatorError):
        optional.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )

    drifted = _planning_proposal(optional.registration, work_intent, context)
    drifted["coordinator_ref"]["coordinator_registration_hash"] = HASH_C
    drifted["proposal_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in drifted.items() if key != "proposal_hash"}
    )
    with pytest.raises(M1ProductPreparationCoordinatorError):
        optional.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
            planning_proposal=drifted,
        )

    admitted = optional.begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
        planning_proposal=_planning_proposal(
            optional.registration, work_intent, context
        ),
    )
    assert admitted["planning_fallback_ref"] is None
    assert deterministic_adapter.calls == []
    assert optional_adapter.calls == [("BEGIN", None)]


def test_product_planning_fallback_replay_rejects_stored_drift() -> None:
    coordinator, adapter, _source, checkpoints, _waits = _coordinator(
        planning_policy=OPTIONAL_POLICY
    )
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
        "planning_fallback_ref": OPTIONAL_POLICY.deterministic_fallback_ref,
    }
    first = coordinator.begin(**values)
    stored = checkpoints.records[first["checkpoint"]["checkpoint_id"]]
    fallback_ref = next(
        item
        for item in stored["authority_refs"]
        if item.get("ref_kind") == "PRODUCT_PLANNING_FALLBACK"
    )
    fallback_ref["fallback_ref"] = "nex-ae:drifted-fallback:v1"

    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        coordinator.begin(**values)

    assert raised.value.error_code == "ae.m1_product_preparation_conflict"
    assert adapter.calls == [("BEGIN", None)]


@pytest.mark.parametrize(
    ("authority_refs", "reader"),
    (
        (
            [
                {"ref_kind": "PRODUCT_PLANNING_FALLBACK", "fallback_ref": "one"},
                {"ref_kind": "PRODUCT_PLANNING_FALLBACK", "fallback_ref": "two"},
            ],
            m1_product_planning_fallback_ref,
        ),
        (
            [{"ref_kind": "PRODUCT_PLANNING_FALLBACK", "fallback_ref": " "}],
            m1_product_planning_fallback_ref,
        ),
        (
            [
                {
                    "ref_kind": "PRODUCT_PLANNING_PROPOSAL",
                    "projection": {"schema_version": "invalid"},
                }
            ],
            m1_product_planning_proposal_ref,
        ),
        (
            [
                {"ref_kind": "PRODUCT_PLANNING_PROPOSAL", "projection": {}},
                {"ref_kind": "PRODUCT_PLANNING_PROPOSAL", "projection": {}},
            ],
            m1_product_planning_proposal_ref,
        ),
    ),
)
def test_product_planning_checkpoint_references_reject_corruption(
    authority_refs, reader
) -> None:
    with pytest.raises(M1ProductPreparationCoordinatorError):
        reader({"authority_refs": authority_refs})


def test_6b2_exact_begin_event_and_ack_loss_replays_without_provider_mutation() -> None:
    coordinator, adapter, source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    first = coordinator.begin(**values)
    replay = coordinator.begin(**values)
    assert replay["replayed"] is True
    assert (
        replay["checkpoint"]["checkpoint_hash"]
        == first["checkpoint"]["checkpoint_hash"]
    )

    event_first = _notify(
        coordinator,
        first["checkpoint"],
        event_id="business-approved-replay",
        evidence_ref=ENVELOPE_ID,
    )
    event_replay = _notify(
        coordinator,
        first["checkpoint"],
        event_id="business-approved-replay",
        evidence_ref=ENVELOPE_ID,
    )
    assert event_first == event_replay
    runtime_job_id = _match(waits, event_id="business-approved-replay")
    advanced = coordinator.resume_approval(
        event_id="business-approved-replay",
        runtime_job_id=runtime_job_id,
        **values,
    )
    ack_loss = coordinator.resume_approval(
        event_id="business-approved-replay",
        runtime_job_id=runtime_job_id,
        **values,
    )

    assert ack_loss["replayed"] is True
    assert (
        ack_loss["checkpoint"]["checkpoint_hash"]
        == advanced["checkpoint"]["checkpoint_hash"]
    )
    assert adapter.calls == [("BEGIN", None), ("BUSINESS", ENVELOPE_ID)]
    assert source.calls == [None, "WAITING_BUSINESS_APPROVAL"]
    assert len(checkpoints.records) == 2
    assert len(waits.events) == 1


def test_6b2_rejects_stale_event_lineage_and_invalid_notification() -> None:
    coordinator, _adapter, _source, _checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    first = coordinator.begin(**values)
    _notify(
        coordinator,
        first["checkpoint"],
        event_id="business-approved-current",
        evidence_ref=ENVELOPE_ID,
    )
    current_job_id = _match(waits, event_id="business-approved-current")
    coordinator.resume_approval(
        event_id="business-approved-current",
        runtime_job_id=current_job_id,
        **values,
    )
    _notify(
        coordinator,
        first["checkpoint"],
        event_id="business-approved-stale",
        evidence_ref=ENVELOPE_ID,
    )
    stale_job_id = _match(waits, event_id="business-approved-stale")
    with pytest.raises(M1ProductPreparationCoordinatorError, match="stale"):
        coordinator.resume_approval(
            event_id="business-approved-stale",
            runtime_job_id=stale_job_id,
            **values,
        )

    current_job_id = _match(waits, event_id="business-approved-current")
    waits.events["business-approved-current"]["event_payload"]["unexpected"] = True
    with pytest.raises(M1ProductPreparationCoordinatorError, match="payload"):
        coordinator._require_event_context(
            waits.load_product_event_context(
                tenant_id=TENANT, event_id="business-approved-current"
            ),
            runtime_job_id=current_job_id,
        )


def test_6b2_fails_closed_on_lineage_drift_and_authority_outage() -> None:
    coordinator, adapter, _source, _checkpoints, _waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    changed = copy.deepcopy(context)
    changed["execution_id"] = "41000000-0000-4000-8000-000000000099"
    with pytest.raises(M1ProductPreparationCoordinatorError, match="lineage"):
        coordinator.begin(
            work_intent=work_intent,
            agent_context=changed,
            capability_snapshot=snapshot,
            execution=execution,
        )
    assert adapter.calls == []

    unavailable, unavailable_adapter, source, _checkpoints, _waits = _coordinator(
        authority_source=_AuthoritySource(fail=True)
    )
    with pytest.raises(M1ProductPreparationCoordinatorError) as raised:
        unavailable.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )
    assert raised.value.retryable is True
    assert source.calls == [None]
    assert unavailable_adapter.calls == []


def test_6b2_constructor_and_notification_boundaries_fail_closed() -> None:
    coordinator, _adapter, _source, _checkpoints, _waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    first = coordinator.begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="not found"):
        coordinator.accept_approval_notification(
            tenant_id=TENANT,
            checkpoint_id="41000000-0000-4000-8000-000000000099",
            event_id="missing",
            notification_ref="wc-event://missing",
            authority_evidence_ref=ENVELOPE_ID,
            received_at=NOW_TEXT,
        )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="invalid"):
        _notify(
            coordinator,
            first["checkpoint"],
            event_id="invalid-evidence",
            evidence_ref="",
        )


def test_6b2_no_fixture_business_values_exist_in_product_coordinator_source() -> None:
    source = (
        ROOT / "services/nex-ae-api/nex_ae_api/m1_product_preparation_coordinator.py"
    ).read_text(encoding="utf-8")
    for residue in (
        "VO00D260101",
        "2450.00",
        "NURIVOICE",
        "employee-100",
        "40/60",
        "fixture",
    ):
        assert (
            residue not in source.lower()
            if residue == "fixture"
            else residue not in source
        )


def test_6b2_constructor_rejects_registration_runtime_and_source_drift() -> None:
    coordinator, adapter, source, checkpoints, waits = _coordinator()
    registration = coordinator.registration
    common = {
        "transaction_preparation": SimpleNamespace(adapter=adapter),
        "authority_source": source,
        "checkpoints": checkpoints,
        "wait_events": waits,
    }
    with pytest.raises(M1ProductPreparationCoordinatorError, match="identity"):
        InstalledM1ProductPlanningCoordinator(
            registration=replace(registration, coordinator_id="OTHER.COORDINATOR"),
            **common,
        )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="runtime"):
        InstalledM1ProductPlanningCoordinator(
            registration=replace(
                registration,
                checkpoint_schema_version="ae.product_preparation_checkpoint.v2",
            ),
            **common,
        )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="runtime"):
        InstalledM1ProductPlanningCoordinator(
            registration=replace(
                registration,
                preparation_adapter_source_identity="different-adapter",
            ),
            **common,
        )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="source"):
        InstalledM1ProductPlanningCoordinator(
            registration=registration,
            **{**common, "authority_source": object()},
        )


def test_6b2_rejects_advanced_begin_missing_wait_and_missing_event() -> None:
    coordinator, _adapter, _source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    first = coordinator.begin(**values)
    checkpoints.records[first["checkpoint"]["checkpoint_id"]]["checkpoint_version"] = 2
    with pytest.raises(M1ProductPreparationCoordinatorError, match="advanced"):
        coordinator.begin(**values)
    checkpoints.records[first["checkpoint"]["checkpoint_id"]]["checkpoint_version"] = 1
    waits.waits.clear()
    waits.wait_bindings.clear()
    with pytest.raises(M1ProductPreparationCoordinatorError, match="wait lineage"):
        _notify(
            coordinator,
            first["checkpoint"],
            event_id="missing-wait",
            evidence_ref=ENVELOPE_ID,
        )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="event"):
        coordinator.resume_approval(
            event_id="missing-event", runtime_job_id="job", **values
        )


def test_6b2_rejects_event_when_latest_checkpoint_disappears() -> None:
    coordinator, _adapter, _source, checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    first = coordinator.begin(**values)
    _notify(
        coordinator,
        first["checkpoint"],
        event_id="missing-latest",
        evidence_ref=ENVELOPE_ID,
    )
    runtime_job_id = _match(waits, event_id="missing-latest")
    checkpoints.latest = lambda **_values: None
    with pytest.raises(M1ProductPreparationCoordinatorError, match="unavailable"):
        coordinator.resume_approval(
            event_id="missing-latest", runtime_job_id=runtime_job_id, **values
        )


def test_6b2_rejects_invalid_stage_projection_and_clock() -> None:
    coordinator, adapter, _source, checkpoints, _waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    adapter.begin_proposal = lambda **_values: _preparation(
        "UNREGISTERED", work_intent["business_context_hash"], {}
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="unregistered"):
        coordinator.begin(**values)
    assert checkpoints.records == {}

    invalid_clock, _adapter, _source, _checkpoints, _waits = _coordinator()
    invalid_clock._clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(M1ProductPreparationCoordinatorError, match="timezone"):
        invalid_clock.begin(**values)

    ready = _preparation("READY_FOR_D04", work_intent["business_context_hash"], {})
    good, _adapter, _source, _checkpoints, _waits = _coordinator()
    lineage = good._lineage(**values)
    ready_checkpoint = good._persist_checkpoint(
        lineage=lineage, preparation=ready, previous=None, causation_id=None
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="not waiting"):
        good.accept_approval_notification(
            tenant_id=TENANT,
            checkpoint_id=ready_checkpoint["checkpoint_id"],
            event_id="ready-event",
            notification_ref="wc-event://ready",
            authority_evidence_ref=EVIDENCE_ID,
            received_at=NOW_TEXT,
        )


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value["wait"].update(state="PENDING"),
        lambda value: value["event"].update(state="RECEIVED"),
        lambda value: value["wait"].update(matched_event_id="other"),
        lambda value: value["wait"].update(resume_runtime_job_id="other"),
        lambda value: value["event"].update(event_type="ACCOUNTING_APPROVAL_CHANGED"),
        lambda value: value["wait_binding"].update(
            expected_event_type="ACCOUNTING_APPROVAL_CHANGED"
        ),
        lambda value: value["event_binding"].update(authority_kind="ACCOUNTING_REVIEW"),
        lambda value: value["wait_binding"].update(authority_kind="ACCOUNTING_REVIEW"),
        lambda value: value["event"].update(external_ref="other"),
        lambda value: value["wait_binding"].update(authority_ref="other"),
    ),
)
def test_6b2_resume_requires_exact_shared_runtime_match(mutator) -> None:
    coordinator, _adapter, _source, _checkpoints, waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    first = coordinator.begin(
        work_intent=work_intent,
        agent_context=context,
        capability_snapshot=snapshot,
        execution=execution,
    )
    _notify(
        coordinator,
        first["checkpoint"],
        event_id="matched-event",
        evidence_ref=ENVELOPE_ID,
    )
    runtime_job_id = _match(waits, event_id="matched-event")
    event_context = waits.load_product_event_context(
        tenant_id=TENANT, event_id="matched-event"
    )
    mutator(event_context)
    with pytest.raises(M1ProductPreparationCoordinatorError, match="stale"):
        coordinator._require_event_context(event_context, runtime_job_id=runtime_job_id)


def test_6b2_rejects_lineage_capability_and_checkpoint_tamper() -> None:
    coordinator, _adapter, _source, checkpoints, _waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    no_capability = copy.deepcopy(snapshot)
    no_capability["capabilities"] = []
    no_capability["snapshot_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in no_capability.items() if key != "snapshot_hash"}
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="snapshot"):
        coordinator.begin(**{**values, "capability_snapshot": no_capability})

    malformed_context = {**context, "identity": None}
    with pytest.raises(M1ProductPreparationCoordinatorError, match="identity"):
        coordinator.begin(**{**values, "agent_context": malformed_context})

    other_snapshot = build_capability_snapshot(
        tenant_id="OTHER",
        capability_snapshot_id="41000000-0000-4000-8000-000000000099",
        snapshot_version=1,
        created_at=NOW_TEXT,
        capabilities=tuple(snapshot["capabilities"]),
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="tenant"):
        coordinator.begin(**{**values, "capability_snapshot": other_snapshot})

    first = coordinator.begin(**values)
    checkpoints.records[first["checkpoint"]["checkpoint_id"]][
        "coordinator_registration_hash"
    ] = HASH_A
    with pytest.raises(M1ProductPreparationCoordinatorError, match="lineage"):
        coordinator.begin(**values)


def test_6b2_rejects_authority_and_checkpoint_projection_tamper() -> None:
    class _CoordinatorFailureSource:
        def resolve(self, **_values):
            raise M1ProductPreparationCoordinatorError("authority", "denied")

    denied, _adapter, _source, _checkpoints, _waits = _coordinator(
        authority_source=_CoordinatorFailureSource()
    )
    work_intent, context, snapshot, execution = _inputs()
    values = {
        "work_intent": work_intent,
        "agent_context": context,
        "capability_snapshot": snapshot,
        "execution": execution,
    }
    with pytest.raises(M1ProductPreparationCoordinatorError, match="denied"):
        denied.begin(**values)

    invalid_type, _adapter, _source, _checkpoints, _waits = _coordinator(
        authority_source=SimpleNamespace(resolve=lambda **_values: object())
    )
    with pytest.raises(M1ProductPreparationCoordinatorError, match="invalid type"):
        invalid_type.begin(**values)

    coordinator, _adapter, _source, _checkpoints, _waits = _coordinator()
    first = coordinator.begin(**values)["checkpoint"]
    missing = {**first, "authority_refs": []}
    with pytest.raises(M1ProductPreparationCoordinatorError, match="unavailable"):
        coordinator_module._preparation_projection(missing)
    drifted = copy.deepcopy(first)
    drifted["authority_refs"][0]["preparation_hash"] = HASH_C
    with pytest.raises(M1ProductPreparationCoordinatorError, match="differs"):
        coordinator_module._preparation_projection(drifted)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    (
        ("intent_revision", 0, "intent_revision"),
        ("intent_hash", "bad", "intent_hash"),
    ),
)
def test_6b2_rejects_invalid_work_intent_scalars(field, value, detail) -> None:
    coordinator, _adapter, _source, _checkpoints, _waits = _coordinator()
    work_intent, context, snapshot, execution = _inputs()
    work_intent[field] = value
    with pytest.raises(M1ProductPreparationCoordinatorError, match=detail):
        coordinator.begin(
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
            execution=execution,
        )
