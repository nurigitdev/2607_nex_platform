from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from mybee_ax.orchestration import M1PreparationAuthority
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from nex_ae_api.m1_product_planning_coordinator import M1_PRODUCT_COORDINATOR_ID
from nex_ae_api.m1_transaction_preparation_runtime import (
    InstalledM1TransactionPreparation,
)
from nex_ae_api.planning_capabilities import (
    CapabilitySnapshotError,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistration,
)
from nex_ae_api.product_planning_proposals import (
    product_planning_proposal_reference,
    validate_product_planning_proposal,
    validate_product_planning_proposal_reference,
)
from nex_ae_api.product_preparation_persistence import (
    PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION,
    SqlAlchemyGeneralizedWaitEventRepository,
    SqlAlchemyProductPreparationCheckpointRepository,
    product_preparation_wait_envelope,
    seal_product_preparation_checkpoint,
    seal_product_preparation_event,
    seal_product_preparation_event_binding,
    seal_product_preparation_wait_binding,
)

M1_PRODUCT_PREPARATION_WAIT_CONTRACT = (
    "contract://nex/ae/product-preparation-wait/m1/v1"
)
M1_PRODUCT_PREPARATION_NOTIFICATION_SCHEMA_VERSION = (
    "ae.product_preparation_notification.v2"
)
_PREPARATION_REF_KIND = "M1_PREPARATION_CHECKPOINT"
_PROPOSAL_REF_KIND = "PRODUCT_PLANNING_PROPOSAL"
_FALLBACK_REF_KIND = "PRODUCT_PLANNING_FALLBACK"
_STAGES = {
    "WAITING_PROPOSAL_REVIEW": (
        "REQUESTER_PROPOSAL_REVIEW",
        "PROPOSAL_REVIEW_SUBMITTED",
        "proposal_review_ref",
    ),
    "WAITING_BUSINESS_APPROVAL": (
        "BUSINESS_FORMAL",
        "BUSINESS_APPROVAL_CHANGED",
        "business_approval_case_id",
    ),
    "WAITING_VOUCHER_REVIEW": (
        "REQUESTER_VOUCHER_REVIEW",
        "VOUCHER_REVIEW_SUBMITTED",
        "voucher_review_ref",
    ),
    "WAITING_ACCOUNTING_APPROVAL": (
        "ACCOUNTING_REVIEW",
        "ACCOUNTING_APPROVAL_CHANGED",
        "accounting_approval_case_id",
    ),
}


@dataclass
class M1ProductPreparationCoordinatorError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class M1PreparationAuthoritySource(Protocol):
    def resolve(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        checkpoint: Mapping[str, Any] | None,
    ) -> M1PreparationAuthority: ...


class InstalledM1ProductPlanningCoordinator:
    """Durable M1 preparation over shared checkpoint and wait/event stores."""

    def __init__(
        self,
        *,
        registration: ProductPlanningCoordinatorRegistration,
        transaction_preparation: InstalledM1TransactionPreparation,
        authority_source: M1PreparationAuthoritySource,
        checkpoints: SqlAlchemyProductPreparationCheckpointRepository,
        wait_events: SqlAlchemyGeneralizedWaitEventRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if registration.coordinator_id != M1_PRODUCT_COORDINATOR_ID:
            raise _invalid("M1 coordinator registration identity is invalid.")
        if (
            registration.checkpoint_schema_version
            != PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION
            or registration.preparation_adapter_source_identity
            != transaction_preparation.adapter.registration.source_identity
        ):
            raise _invalid("M1 coordinator registration differs from its runtime.")
        if not callable(getattr(authority_source, "resolve", None)):
            raise _invalid("M1 preparation authority source is unavailable.")
        self.registration = registration
        self._preparation = transaction_preparation
        self._authority_source = authority_source
        self._checkpoints = checkpoints
        self._wait_events = wait_events
        self._clock = clock or (lambda: datetime.now(UTC))

    def begin(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
        planning_proposal: Mapping[str, Any] | None = None,
        planning_fallback_ref: str | None = None,
    ) -> dict[str, Any]:
        lineage = self._lineage(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        latest = self._latest(lineage)
        proposal_ref = self._proposal_reference(planning_proposal)
        fallback_ref = self._fallback_reference(
            planning_fallback_ref,
            proposal_ref=proposal_ref,
        )
        if latest is not None:
            self._require_checkpoint_lineage(latest, lineage)
            if m1_product_planning_proposal_ref(latest) != proposal_ref:
                raise _conflict("M1 Product planning proposal replay has drifted.")
            if m1_product_planning_fallback_ref(latest) != fallback_ref:
                raise _conflict("M1 Product planning fallback replay has drifted.")
            if latest["checkpoint_version"] != 1:
                raise _conflict("M1 preparation has already advanced beyond begin.")
            return self._result(latest, replayed=True)
        authority = self._resolve_authority(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
            checkpoint=None,
        )
        preparation = self._preparation.adapter.begin_proposal(
            business_request_context=work_intent["business_request_context"],
            business_context_hash=work_intent["business_context_hash"],
            authority=authority,
            parent_execution_id=lineage["agent_execution_id"],
        )
        checkpoint = self._persist_checkpoint(
            lineage=lineage,
            preparation=preparation,
            previous=None,
            causation_id=work_intent["source"]["source_ref"],
            proposal_ref=proposal_ref,
            fallback_ref=fallback_ref,
        )
        return self._result(checkpoint, replayed=False)

    def replay_begin(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Return an exact started Product preparation without recalling a provider."""
        lineage = self._lineage(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        latest = self._latest(lineage)
        if latest is None:
            return None
        self._require_checkpoint_lineage(latest, lineage)
        if latest["checkpoint_version"] != 1:
            raise _conflict("M1 preparation has already advanced beyond begin.")
        return self._result(latest, replayed=True)

    def accept_approval_notification(
        self,
        *,
        tenant_id: str,
        checkpoint_id: str,
        event_id: str,
        notification_ref: str,
        authority_evidence_ref: str,
        received_at: str,
        authority_state: str = "APPROVED",
    ) -> dict[str, Any]:
        checkpoint = self._checkpoints.get(
            tenant_id=tenant_id, checkpoint_id=checkpoint_id
        )
        if checkpoint is None:
            raise _not_found("M1 preparation checkpoint was not found.")
        stage = _stage(checkpoint["stage"])
        authority_kind, event_type, authority_key = stage
        preparation = m1_preparation_projection(checkpoint)
        authority_ref = _text(
            preparation["references"].get(authority_key), authority_key, 512
        )
        wait_id = _wait_id(checkpoint)
        wait_context = self._wait_events.load_product_wait_context(
            tenant_id=tenant_id, wait_id=wait_id
        )
        if (
            wait_context is None
            or wait_context["checkpoint"]["checkpoint_hash"]
            != checkpoint["checkpoint_hash"]
        ):
            raise _conflict("M1 preparation wait lineage is unavailable.")
        payload = {
            "schema_version": M1_PRODUCT_PREPARATION_NOTIFICATION_SCHEMA_VERSION,
            "notification_ref": _text(notification_ref, "notification_ref", 512),
            "authority_evidence_ref": _text(
                authority_evidence_ref, "authority_evidence_ref", 512
            ),
            "authority_state": _authority_state(authority_state),
        }
        event = seal_product_preparation_event(
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "event_type": event_type,
                "external_ref": authority_ref,
                "event_payload": payload,
                "received_at": received_at,
            }
        )
        binding = seal_product_preparation_event_binding(
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "wait_id": wait_id,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "checkpoint_hash": checkpoint["checkpoint_hash"],
                "coordinator_id": self.registration.coordinator_id,
                "coordinator_version": self.registration.coordinator_version,
                "coordinator_registration_hash": (self.registration.registration_hash),
                "authority_kind": authority_kind,
                "notification_ref": payload["notification_ref"],
                "agent_execution_id": checkpoint["agent_execution_id"],
                "work_intent_id": checkpoint["work_intent_id"],
                "created_at": received_at,
            }
        )
        return self._wait_events.accept_event(event, product_binding=binding)

    def resume_approval(
        self,
        *,
        event_id: str,
        runtime_job_id: str,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        lineage = self._lineage(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        context = self._wait_events.load_product_event_context(
            tenant_id=lineage["tenant_id"], event_id=event_id
        )
        if context is None:
            raise _not_found("M1 preparation approval event was not found.")
        previous = context["checkpoint"]
        self._require_checkpoint_lineage(previous, lineage)
        self._require_event_context(context, runtime_job_id=runtime_job_id)
        latest = self._latest(lineage)
        if latest is None:
            raise _conflict("M1 preparation checkpoint lineage is unavailable.")
        if latest["checkpoint_id"] != previous["checkpoint_id"]:
            if (
                latest["previous_checkpoint_id"] == previous["checkpoint_id"]
                and latest["causation_id"] == event_id
            ):
                return self._result(latest, replayed=True)
            raise _conflict("M1 preparation approval event is stale or out of order.")
        preparation = m1_preparation_projection(previous)
        payload = context["event"]["event_payload"]
        evidence_ref = _text(
            payload.get("authority_evidence_ref"),
            "authority_evidence_ref",
            512,
        )
        authority_state = _authority_state(payload.get("authority_state", "APPROVED"))
        if authority_state == "REJECTED":
            if previous["stage"] in {
                "WAITING_PROPOSAL_REVIEW",
                "WAITING_VOUCHER_REVIEW",
            }:
                raise _conflict("Requester review submission cannot be rejected.")
            advanced = _terminal_preparation(
                preparation,
                terminal_stage=_rejection_terminal_state(self.registration),
                authority_evidence_ref=evidence_ref,
            )
            checkpoint = self._persist_checkpoint(
                lineage=lineage,
                preparation=advanced,
                previous=previous,
                causation_id=event_id,
                proposal_ref=m1_product_planning_proposal_ref(previous),
                fallback_ref=m1_product_planning_fallback_ref(previous),
            )
            return self._result(checkpoint, replayed=False)
        authority = self._resolve_authority(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
            checkpoint=previous,
        )
        if previous["stage"] == "WAITING_PROPOSAL_REVIEW":
            advanced = self._preparation.adapter.continue_after_proposal_review(
                business_request_context=work_intent["business_request_context"],
                business_context_hash=work_intent["business_context_hash"],
                authority=authority,
                parent_execution_id=lineage["agent_execution_id"],
            )
        elif previous["stage"] == "WAITING_BUSINESS_APPROVAL":
            advanced = self._preparation.adapter.continue_after_business_approval(
                business_request_context=work_intent["business_request_context"],
                business_context_hash=work_intent["business_context_hash"],
                authority=authority,
                parent_execution_id=lineage["agent_execution_id"],
                envelope_id=_approved_document_envelope_ref(evidence_ref),
            )
        elif previous["stage"] == "WAITING_VOUCHER_REVIEW":
            candidate_id = _text(
                preparation["references"].get("candidate_id"),
                "candidate_id",
                512,
            )
            advanced = self._preparation.adapter.continue_after_voucher_review(
                business_request_context=work_intent["business_request_context"],
                business_context_hash=work_intent["business_context_hash"],
                authority=authority,
                parent_execution_id=lineage["agent_execution_id"],
                candidate_id=candidate_id,
            )
        else:
            candidate_id = _text(
                preparation["references"].get("candidate_id"),
                "candidate_id",
                512,
            )
            advanced = self._preparation.adapter.continue_after_accounting_approval(
                business_request_context=work_intent["business_request_context"],
                business_context_hash=work_intent["business_context_hash"],
                authority=authority,
                parent_execution_id=lineage["agent_execution_id"],
                candidate_id=candidate_id,
                accounting_approval_evidence_id=evidence_ref,
            )
        checkpoint = self._persist_checkpoint(
            lineage=lineage,
            preparation=advanced,
            previous=previous,
            causation_id=event_id,
            proposal_ref=m1_product_planning_proposal_ref(previous),
            fallback_ref=m1_product_planning_fallback_ref(previous),
        )
        return self._result(checkpoint, replayed=False)

    def load_ready_checkpoint(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Load the exact latest READY checkpoint without mutating runtime state."""
        lineage = self._lineage(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        checkpoint = self._latest(lineage)
        if checkpoint is None:
            raise _not_found("M1 preparation checkpoint was not found.")
        self._require_checkpoint_lineage(checkpoint, lineage)
        if (
            checkpoint.get("stage") != self.registration.ready_state
            or checkpoint.get("stage_kind") != "READY"
        ):
            raise _conflict("M1 preparation is not ready for plan activation.")
        return {
            "checkpoint": dict(checkpoint),
            "preparation": m1_preparation_projection(checkpoint),
            "planning_proposal_ref": m1_product_planning_proposal_ref(checkpoint),
            "planning_fallback_ref": m1_product_planning_fallback_ref(checkpoint),
        }

    def _persist_checkpoint(
        self,
        *,
        lineage: Mapping[str, Any],
        preparation: Mapping[str, Any],
        previous: Mapping[str, Any] | None,
        causation_id: str | None,
        proposal_ref: Mapping[str, Any] | None = None,
        fallback_ref: str | None = None,
    ) -> dict[str, Any]:
        stage = str(preparation.get("stage") or "")
        if stage not in {
            *_STAGES,
            self.registration.ready_state,
            *self.registration.terminal_states,
        }:
            raise _conflict("M1 preparation returned an unregistered stage.")
        preparation_hash = _hash(
            preparation.get("preparation_hash"), "preparation_hash"
        )
        version = 1 if previous is None else int(previous["checkpoint_version"]) + 1
        checkpoint_id = str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/ae/product-preparation/checkpoint/"
                f"{lineage['tenant_id']}/{lineage['agent_execution_id']}/"
                f"{version}/{preparation_hash}",
            )
        )
        authority_refs = [
            {
                "ref_kind": _PREPARATION_REF_KIND,
                "preparation_hash": preparation_hash,
                "projection": dict(preparation),
            }
        ]
        if proposal_ref is not None:
            authority_refs.append(
                {
                    "ref_kind": _PROPOSAL_REF_KIND,
                    "projection": validate_product_planning_proposal_reference(
                        proposal_ref
                    ),
                }
            )
        if fallback_ref is not None:
            authority_refs.append(
                {
                    "ref_kind": _FALLBACK_REF_KIND,
                    "fallback_ref": fallback_ref,
                }
            )
        if stage in _STAGES:
            authority_kind, _event_type, authority_key = _STAGES[stage]
            authority_refs.append(
                {
                    "authority_kind": authority_kind,
                    "authority_ref": _text(
                        preparation["references"].get(authority_key),
                        authority_key,
                        512,
                    ),
                }
            )
        created_at = _timestamp(self._clock())
        checkpoint = seal_product_preparation_checkpoint(
            {
                **lineage,
                "checkpoint_id": checkpoint_id,
                "checkpoint_schema_version": (
                    PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION
                ),
                "checkpoint_version": version,
                "previous_checkpoint_id": (
                    None if previous is None else previous["checkpoint_id"]
                ),
                "previous_checkpoint_hash": (
                    None if previous is None else previous["checkpoint_hash"]
                ),
                "coordinator_id": self.registration.coordinator_id,
                "coordinator_version": self.registration.coordinator_version,
                "coordinator_registration_hash": (self.registration.registration_hash),
                "preparation_adapter_source_identity": (
                    self.registration.preparation_adapter_source_identity
                ),
                "materializer_source_identity": (
                    self.registration.materializer_source_identity
                ),
                "stage": stage,
                "stage_kind": (
                    "WAITING"
                    if stage in _STAGES
                    else "READY"
                    if stage == self.registration.ready_state
                    else "TERMINAL"
                ),
                "authority_refs": authority_refs,
                "idempotency_key": (
                    f"product-preparation:{lineage['agent_execution_id']}:"
                    f"v{version}:{preparation_hash}"
                ),
                "correlation_id": lineage["agent_execution_id"],
                "causation_id": causation_id,
                "created_at": created_at,
            }
        )
        saved = self._checkpoints.append(checkpoint)
        if stage in _STAGES:
            self._ensure_wait(saved, created_at=created_at)
        return saved

    def _ensure_wait(
        self, checkpoint: Mapping[str, Any], *, created_at: str | None = None
    ) -> dict[str, Any]:
        authority_kind, event_type, authority_key = _stage(checkpoint["stage"])
        preparation = m1_preparation_projection(checkpoint)
        authority_ref = _text(
            preparation["references"].get(authority_key), authority_key, 512
        )
        created = created_at or _timestamp(self._clock())
        wait_id = _wait_id(checkpoint)
        wait = product_preparation_wait_envelope(
            {
                "tenant_id": checkpoint["tenant_id"],
                "wait_id": wait_id,
                "agent_execution_id": checkpoint["agent_execution_id"],
                "external_ref": authority_ref,
                "wait_contract_ref": M1_PRODUCT_PREPARATION_WAIT_CONTRACT,
                "created_at": created,
            }
        )
        binding = seal_product_preparation_wait_binding(
            {
                "tenant_id": checkpoint["tenant_id"],
                "wait_id": wait_id,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "checkpoint_hash": checkpoint["checkpoint_hash"],
                "coordinator_id": self.registration.coordinator_id,
                "coordinator_version": self.registration.coordinator_version,
                "coordinator_registration_hash": (self.registration.registration_hash),
                "expected_event_type": event_type,
                "authority_kind": authority_kind,
                "authority_ref": authority_ref,
                "agent_execution_id": checkpoint["agent_execution_id"],
                "work_intent_id": checkpoint["work_intent_id"],
                "created_at": created,
            }
        )
        return self._wait_events.register_wait(wait, product_binding=binding)

    def _result(
        self, checkpoint: Mapping[str, Any], *, replayed: bool
    ) -> dict[str, Any]:
        wait = None
        if checkpoint["stage"] in _STAGES:
            wait = self._ensure_wait(checkpoint)
        return {
            "checkpoint": dict(checkpoint),
            "wait": wait,
            "replayed": replayed,
            "ready": checkpoint["stage"] == self.registration.ready_state,
            "terminal": checkpoint["stage"] in self.registration.terminal_states,
            "planning_proposal_ref": m1_product_planning_proposal_ref(checkpoint),
            "planning_fallback_ref": m1_product_planning_fallback_ref(checkpoint),
        }

    def _latest(self, lineage: Mapping[str, Any]) -> dict[str, Any] | None:
        return self._checkpoints.latest(
            tenant_id=lineage["tenant_id"],
            agent_execution_id=lineage["agent_execution_id"],
            coordinator_id=self.registration.coordinator_id,
            coordinator_version=self.registration.coordinator_version,
        )

    def _lineage(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            snapshot = validate_capability_snapshot_contract(capability_snapshot)
            capability_by_exact_version(
                snapshot,
                self.registration.capability_id,
                self.registration.capability_version,
            )
        except CapabilitySnapshotError as exc:
            raise _invalid("M1 capability snapshot is not admitted.") from exc
        execution_id = _text(work_intent.get("execution_id"), "execution_id", 64)
        if (
            agent_context.get("execution_id") != execution_id
            or execution.get("execution_id") != execution_id
        ):
            raise _conflict("M1 execution lineage differs.")
        identity = agent_context.get("identity")
        if not isinstance(identity, Mapping):
            raise _invalid("M1 AgentContext identity is unavailable.")
        tenant_id = _text(identity.get("tenant_id"), "tenant_id", 128)
        if snapshot["tenant_id"] != tenant_id:
            raise _conflict("M1 capability tenant differs.")
        requester_ref = identity.get("subject_id") or identity.get("principal_id")
        return {
            "tenant_id": tenant_id,
            "agent_execution_id": execution_id,
            "requester_ref": _text(requester_ref, "requester_ref", 200),
            "work_intent_id": _text(
                work_intent.get("work_intent_id"), "work_intent_id", 64
            ),
            "work_intent_revision": _positive_int(
                work_intent.get("intent_revision"), "intent_revision"
            ),
            "work_intent_hash": _hash(work_intent.get("intent_hash"), "intent_hash"),
            "agent_context_id": _text(
                agent_context.get("context_id"), "context_id", 64
            ),
            "context_generation": _positive_int(
                agent_context.get("context_generation"), "context_generation"
            ),
            "context_hash": _hash(agent_context.get("context_hash"), "context_hash"),
            "business_context_hash": _hash(
                work_intent.get("business_context_hash"), "business_context_hash"
            ),
            "capability_id": self.registration.capability_id,
            "capability_version": self.registration.capability_version,
            "capability_release_ref": (
                "product-capability://"
                f"{self.registration.capability_id}/"
                f"{self.registration.capability_version}/"
                f"{self.registration.trigger_capability.capability_registration_hash}"
            ),
            "capability_registration_hash": (
                self.registration.trigger_capability.capability_registration_hash
            ),
        }

    def _require_checkpoint_lineage(
        self, checkpoint: Mapping[str, Any], lineage: Mapping[str, Any]
    ) -> None:
        fields = tuple(lineage) + (
            "coordinator_id",
            "coordinator_version",
            "coordinator_registration_hash",
            "preparation_adapter_source_identity",
            "materializer_source_identity",
        )
        expected = {
            **lineage,
            "coordinator_id": self.registration.coordinator_id,
            "coordinator_version": self.registration.coordinator_version,
            "coordinator_registration_hash": self.registration.registration_hash,
            "preparation_adapter_source_identity": (
                self.registration.preparation_adapter_source_identity
            ),
            "materializer_source_identity": self.registration.materializer_source_identity,
        }
        if any(checkpoint.get(field) != expected[field] for field in fields):
            raise _conflict("M1 preparation checkpoint lineage differs.")

    def _require_event_context(
        self, context: Mapping[str, Any], *, runtime_job_id: str
    ) -> None:
        event = context["event"]
        wait = context["wait"]
        wait_binding = context["wait_binding"]
        event_binding = context["event_binding"]
        checkpoint = context["checkpoint"]
        stage = _stage(checkpoint["stage"])
        authority_kind, event_type, _authority_key = stage
        if (
            wait.get("state") != "RESUME_QUEUED"
            or event.get("state") != "MATCHED"
            or wait.get("matched_event_id") != event.get("event_id")
            or wait.get("resume_runtime_job_id")
            != _text(runtime_job_id, "runtime_job_id", 64)
            or event["event_type"] != event_type
            or wait_binding["expected_event_type"] != event_type
            or event_binding["authority_kind"] != authority_kind
            or wait_binding["authority_kind"] != authority_kind
            or event["external_ref"] != wait["external_ref"]
            or event["external_ref"] != wait_binding["authority_ref"]
        ):
            raise _conflict("M1 approval event is stale or out of order.")
        payload = event["event_payload"]
        legacy_fields = {
            "schema_version",
            "notification_ref",
            "authority_evidence_ref",
        }
        current_fields = legacy_fields | {"authority_state"}
        legacy = (
            set(payload) == legacy_fields
            and payload.get("schema_version")
            == "ae.product_preparation_notification.v1"
        )
        current = (
            set(payload) == current_fields
            and payload.get("schema_version")
            == M1_PRODUCT_PREPARATION_NOTIFICATION_SCHEMA_VERSION
        )
        if (
            not (legacy or current)
            or payload["notification_ref"] != event_binding["notification_ref"]
            or (
                current
                and payload.get("authority_state") not in {"APPROVED", "REJECTED"}
            )
        ):
            raise _conflict("M1 approval event payload is invalid.")

    def _resolve_authority(self, **values: Any) -> M1PreparationAuthority:
        try:
            authority = self._authority_source.resolve(**values)
        except M1ProductPreparationCoordinatorError:
            raise
        except Exception as exc:
            raise _unavailable("M1 preparation authority reload failed.") from exc
        if not isinstance(authority, M1PreparationAuthority):
            raise _invalid("M1 preparation authority source returned an invalid type.")
        return authority

    def _proposal_reference(
        self, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        mode = self.registration.planning_policy.mode
        if value is None:
            if mode == "PROVIDER_ASSISTED_REQUIRED":
                raise _invalid("M1 Product planning proposal is required.")
            return None
        if mode == "DETERMINISTIC_ONLY":
            raise _invalid("M1 deterministic-only planning rejects a proposal.")
        try:
            proposal = validate_product_planning_proposal(value)
        except ValueError as exc:
            raise _invalid("M1 Product planning proposal is invalid.") from exc
        coordinator = proposal["coordinator_ref"]
        if (
            coordinator.get("coordinator_id") != self.registration.coordinator_id
            or coordinator.get("coordinator_version")
            != self.registration.coordinator_version
            or coordinator.get("coordinator_registration_hash")
            != self.registration.registration_hash
            or proposal.get("planning_policy")
            != self.registration.planning_policy.projection()
        ):
            raise _conflict("M1 Product planning proposal registration has drifted.")
        return product_planning_proposal_reference(proposal)

    def _fallback_reference(
        self,
        value: str | None,
        *,
        proposal_ref: Mapping[str, Any] | None,
    ) -> str | None:
        policy = self.registration.planning_policy
        if policy.mode != "PROVIDER_ASSISTED_OPTIONAL":
            if value is not None:
                raise _invalid("M1 Product planning fallback is not admitted.")
            return None
        if proposal_ref is not None:
            if value is not None:
                raise _invalid("M1 Product planning selection is ambiguous.")
            return None
        if value != policy.deterministic_fallback_ref:
            raise _invalid("M1 Product planning fallback is unavailable or drifted.")
        return value


def m1_preparation_projection(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    matches = [
        item
        for item in checkpoint.get("authority_refs", ())
        if isinstance(item, Mapping) and item.get("ref_kind") == _PREPARATION_REF_KIND
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("projection"), Mapping):
        raise _conflict("M1 preparation projection is unavailable.")
    projection = dict(matches[0]["projection"])
    if matches[0].get("preparation_hash") != projection.get(
        "preparation_hash"
    ) or checkpoint.get("business_context_hash") != projection.get(
        "business_context_hash"
    ):
        raise _conflict("M1 preparation projection differs from checkpoint lineage.")
    return projection


def m1_product_planning_proposal_ref(
    checkpoint: Mapping[str, Any],
) -> dict[str, Any] | None:
    matches = [
        item
        for item in checkpoint.get("authority_refs", ())
        if isinstance(item, Mapping) and item.get("ref_kind") == _PROPOSAL_REF_KIND
    ]
    if not matches:
        return None
    if len(matches) != 1 or not isinstance(matches[0].get("projection"), Mapping):
        raise _conflict("M1 Product planning proposal reference is invalid.")
    try:
        return validate_product_planning_proposal_reference(matches[0]["projection"])
    except ValueError as exc:
        raise _conflict("M1 Product planning proposal reference has drifted.") from exc


def m1_product_planning_fallback_ref(
    checkpoint: Mapping[str, Any],
) -> str | None:
    matches = [
        item
        for item in checkpoint.get("authority_refs", ())
        if isinstance(item, Mapping) and item.get("ref_kind") == _FALLBACK_REF_KIND
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise _conflict("M1 Product planning fallback reference is invalid.")
    fallback_ref = matches[0].get("fallback_ref")
    if not isinstance(fallback_ref, str) or not fallback_ref.strip():
        raise _conflict("M1 Product planning fallback reference has drifted.")
    return fallback_ref.strip()


_preparation_projection = m1_preparation_projection


def _stage(value: object) -> tuple[str, str, str]:
    stage = str(value or "")
    result = _STAGES.get(stage)
    if result is None:
        raise _conflict("M1 preparation is not waiting for approval.")
    return result


def _wait_id(checkpoint: Mapping[str, Any]) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/product-preparation/wait/"
            f"{checkpoint['tenant_id']}/{checkpoint['checkpoint_hash']}",
        )
    )


def _terminal_preparation(
    preparation: Mapping[str, Any],
    *,
    terminal_stage: str,
    authority_evidence_ref: str,
) -> dict[str, Any]:
    semantics = {
        key: item for key, item in preparation.items() if key != "preparation_hash"
    }
    references = dict(_mapping(semantics.get("references"), "references"))
    references.update(
        {
            "authority_outcome": "REJECTED",
            "authority_evidence_ref": authority_evidence_ref,
        }
    )
    semantics.update(stage=terminal_stage, references=references)
    return {**semantics, "preparation_hash": semantic_sha256_hash_ref(semantics)}


def _rejection_terminal_state(
    registration: ProductPlanningCoordinatorRegistration,
) -> str:
    matches = [
        state for state in registration.terminal_states if "CANCEL" in state.upper()
    ]
    if len(matches) != 1:
        raise _conflict(
            "Product coordinator lacks one approval-rejection terminal state."
        )
    return matches[0]


def _authority_state(value: object) -> str:
    admitted = _text(value, "authority_state", 32)
    if admitted not in {"APPROVED", "REJECTED"}:
        raise _invalid("authority_state is invalid.")
    return admitted


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _conflict(f"M1 preparation {field} is unavailable.")
    return value


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("M1 Product Coordinator clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _approved_document_envelope_ref(value: object) -> str:
    candidate = _text(value, "approved_document_envelope_id", 36)
    try:
        admitted = str(UUID(candidate))
    except ValueError as exc:
        raise _invalid("approved_document_envelope_id is invalid.") from exc
    if candidate != admitted:
        raise _invalid("approved_document_envelope_id is not canonical.")
    return admitted


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} is invalid.")
    return value.strip()


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _invalid(f"{field} is invalid.")
    return value


def _hash(value: object, field: str) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _invalid(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "ae.m1_product_preparation_invalid", detail
    )


def _conflict(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "ae.m1_product_preparation_conflict", detail
    )


def _not_found(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "ae.m1_product_preparation_not_found", detail
    )


def _unavailable(detail: str) -> M1ProductPreparationCoordinatorError:
    return M1ProductPreparationCoordinatorError(
        "ae.m1_product_preparation_unavailable", detail, True
    )
