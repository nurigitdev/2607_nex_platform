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
    build_m1_product_planning_coordinator_registration,
)
from nex_ae_api.m1_product_preparation_coordinator import (
    InstalledM1ProductPlanningCoordinator,
    M1ProductPreparationCoordinatorError,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_capabilities import load_product_capability_registry
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
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
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


def _coordinator(*, authority_source=None):
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )
    adapter = _PreparationAdapter()
    registration = build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=adapter.registration,
    )
    checkpoints = _CheckpointRepository()
    waits = _WaitEventRepository(checkpoints)
    source = authority_source or _AuthoritySource()
    coordinator = InstalledM1ProductPlanningCoordinator(
        registration=registration,
        transaction_preparation=SimpleNamespace(adapter=adapter),
        authority_source=source,
        checkpoints=checkpoints,
        wait_events=waits,
        clock=lambda: NOW,
    )
    return coordinator, adapter, source, checkpoints, waits


def _notify(coordinator, checkpoint, *, event_id, evidence_ref):
    return coordinator.accept_approval_notification(
        tenant_id=TENANT,
        checkpoint_id=checkpoint["checkpoint_id"],
        event_id=event_id,
        notification_ref=f"wc-event://{event_id}",
        authority_evidence_ref=evidence_ref,
        received_at=NOW_TEXT,
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
