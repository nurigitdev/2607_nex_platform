from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from mybee_ax.integrations import M1_ALLOCATION_CAPABILITY_ID
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.accounting_allocation_authority import (
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.accounting_allocation_intent_activation import (
    ACCOUNTING_ALLOCATION_BINDING_FIELD,
)
from nex_ae_api.planning_capabilities import (
    LOCAL_SKILL_EXECUTOR_KIND,
    capability_by_exact_version,
    validate_capability_snapshot_contract,
)
from nex_ae_api.product_capabilities import ProductCapabilityRegistry
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistration,
    ProductPlanningPolicy,
    ProductPlanningReplayPolicy,
    build_product_planning_coordinator_registration,
    capability_binding,
    skill_bundle_lock,
)
from nex_ae_api.product_preparation_persistence import (
    PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION,
    SqlAlchemyProductPreparationCheckpointRepository,
    seal_product_preparation_checkpoint,
)

ACCOUNTING_ALLOCATION_COORDINATOR_ID = "MYBEE.ACCOUNTING.ALLOCATION"
ACCOUNTING_ALLOCATION_COORDINATOR_VERSION = "1.0.0"
ACCOUNTING_ALLOCATION_COORDINATOR_IMPLEMENTATION_REF = (
    "nex_ae_api.accounting_allocation_product_coordinator:"
    "InstalledAccountingAllocationProductCoordinator"
)
ACCOUNTING_ALLOCATION_PREPARATION_SOURCE_IDENTITY = (
    "nex-ae:accounting-allocation-immediate-preparation:v1"
)
ACCOUNTING_ALLOCATION_MATERIALIZER_SOURCE_IDENTITY = (
    "nex-ae:accounting-allocation-plan-materializer:ae.accounting_allocation_plan.v1"
)
ACCOUNTING_ALLOCATION_READY_STATE = "READY_FOR_ACCOUNTING_ALLOCATION"
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ACCOUNTING_ALLOCATION_ACTIVATION_PATH = (
    ROOT
    / "deployment/locks/ae-accounting-allocation-product-coordinator-activation.v1.json"
)
DEFAULT_ACCOUNTING_ALLOCATION_ROLLBACK_PATH = (
    ROOT
    / "deployment/locks/ae-accounting-allocation-product-coordinator-rollback.v1.json"
)
ACCOUNTING_ALLOCATION_PLANNING_POLICY = ProductPlanningPolicy(
    mode="DETERMINISTIC_ONLY",
    proposal_schema_version="ae.product_planning_proposal.v1",
    prompt_binding_key="ae.accounting_allocation.deterministic.v1",
    admission_policy_ref="ae.accounting_allocation.candidate.strict.v1",
    deterministic_fallback_ref=None,
    proposal_consumers=(),
)
ACCOUNTING_ALLOCATION_REPLAY_POLICY = ProductPlanningReplayPolicy(
    policy_id="ae.accounting_allocation.exact.v1",
    exact_event_replay="RETURN_ORIGINAL_RESUME",
    semantic_drift="FAIL_CLOSED_ZERO_MUTATION",
    stale_or_out_of_order="DENY",
    ack_loss_redelivery="CONVERGE",
)


@dataclass(frozen=True)
class AccountingAllocationProductCoordinatorError(RuntimeError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AccountingAllocationCoordinatorAdmission:
    registration: ProductPlanningCoordinatorRegistration
    activation_lock: Mapping[str, Any]
    rollback_receipt: Mapping[str, Any]


def build_accounting_allocation_product_coordinator_registration(
    *,
    product_capabilities: ProductCapabilityRegistry,
    activation_status: str = "CONTRACT_ONLY",
) -> ProductPlanningCoordinatorRegistration:
    allocation = product_capabilities.resolve(
        M1_ALLOCATION_CAPABILITY_ID, required=True
    )
    if (
        allocation is None
        or allocation.capability.get("operation_semantics") != "WRITE"
        or allocation.capability.get("status") != "ACTIVE"
    ):
        raise _invalid("Allocation Product capability is not an active WRITE.")
    return build_product_planning_coordinator_registration(
        coordinator_id=ACCOUNTING_ALLOCATION_COORDINATOR_ID,
        coordinator_version=ACCOUNTING_ALLOCATION_COORDINATOR_VERSION,
        activation_status=activation_status,
        implementation_ref=ACCOUNTING_ALLOCATION_COORDINATOR_IMPLEMENTATION_REF,
        trigger_capability=capability_binding(allocation),
        required_capabilities=(capability_binding(allocation),),
        preparation_adapter_source_identity=(
            ACCOUNTING_ALLOCATION_PREPARATION_SOURCE_IDENTITY
        ),
        materializer_source_identity=(
            ACCOUNTING_ALLOCATION_MATERIALIZER_SOURCE_IDENTITY
        ),
        initial_state="ALLOCATION_ADMISSION_PENDING",
        waiting_states=("WAITING_ALLOCATION_AUTHORITY",),
        ready_state=ACCOUNTING_ALLOCATION_READY_STATE,
        terminal_states=("ALLOCATION_PREPARATION_FAILED",),
        required_operations=(M1_ALLOCATION_CAPABILITY_ID,),
        checkpoint_schema_version=PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION,
        replay_policy=ACCOUNTING_ALLOCATION_REPLAY_POLICY,
        planning_policy=ACCOUNTING_ALLOCATION_PLANNING_POLICY,
        supported_executor_kinds=(LOCAL_SKILL_EXECUTOR_KIND,),
        installed_skill_bundle_locks=(skill_bundle_lock(allocation),),
    )


class InstalledAccountingAllocationProductCoordinator:
    """Persist an immediate READY checkpoint for a typed allocation intent."""

    def __init__(
        self,
        *,
        registration: ProductPlanningCoordinatorRegistration,
        checkpoints: SqlAlchemyProductPreparationCheckpointRepository,
    ) -> None:
        if (
            registration.coordinator_id != ACCOUNTING_ALLOCATION_COORDINATOR_ID
            or registration.ready_state != ACCOUNTING_ALLOCATION_READY_STATE
            or not callable(getattr(checkpoints, "append", None))
            or not callable(getattr(checkpoints, "latest", None))
        ):
            raise _invalid("Allocation Product coordinator dependencies differ.")
        self.registration = registration
        self._checkpoints = checkpoints

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
        if planning_proposal is not None or planning_fallback_ref is not None:
            raise _invalid("Deterministic allocation does not admit a plan proposal.")
        checkpoint = self._checkpoint(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        latest = self._checkpoints.latest(
            tenant_id=str(checkpoint["tenant_id"]),
            agent_execution_id=str(checkpoint["agent_execution_id"]),
            coordinator_id=self.registration.coordinator_id,
            coordinator_version=self.registration.coordinator_version,
        )
        replayed = latest is not None
        if latest is not None and latest != checkpoint:
            raise _conflict("Allocation Product checkpoint replay has drifted.")
        saved = latest or self._checkpoints.append(checkpoint)
        return {
            "checkpoint": saved,
            "ready": True,
            "terminal": False,
            "replayed": replayed,
        }

    def replay_begin(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        desired = self._checkpoint(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        latest = self._checkpoints.latest(
            tenant_id=str(desired["tenant_id"]),
            agent_execution_id=str(desired["agent_execution_id"]),
            coordinator_id=self.registration.coordinator_id,
            coordinator_version=self.registration.coordinator_version,
        )
        if latest is None:
            return None
        if latest != desired:
            raise _conflict("Allocation Product checkpoint replay has drifted.")
        return {
            "checkpoint": latest,
            "ready": True,
            "terminal": False,
            "replayed": True,
        }

    def accept_approval_notification(self, **_values: Any) -> Mapping[str, Any]:
        raise _invalid("Allocation Product coordinator has no approval wait.")

    def resume_approval(self, **_values: Any) -> Mapping[str, Any]:
        raise _invalid("Allocation Product coordinator has no approval resume.")

    def _checkpoint(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        allocation = validate_accounting_allocation_work_intent(
            work_intent.get(ACCOUNTING_ALLOCATION_BINDING_FIELD)
        )
        snapshot = validate_capability_snapshot_contract(capability_snapshot)
        installed = capability_by_exact_version(
            snapshot,
            self.registration.capability_id,
            self.registration.capability_version,
        )
        context_identity = agent_context.get("identity")
        if (
            work_intent.get("work_intent_id") != allocation["work_intent_id"]
            or work_intent.get("execution_id") != allocation["execution_id"]
            or execution.get("execution_id") != allocation["execution_id"]
            or agent_context.get("execution_id") != allocation["execution_id"]
            or not isinstance(context_identity, Mapping)
            or context_identity.get("tenant_id") != allocation["tenant_id"]
            or context_identity.get("principal_id") != allocation["subject_id"]
            or installed.get("capability_id") != self.registration.capability_id
        ):
            raise _conflict("Allocation Product coordinator lineage differs.")
        lock = self.registration.installed_skill_bundle_locks[0]
        checkpoint_id = str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/ae/accounting-allocation/checkpoint/"
                f"{allocation['tenant_id']}/{allocation['execution_id']}/"
                f"{allocation['intent_hash']}",
            )
        )
        source = work_intent.get("source")
        if not isinstance(source, Mapping):
            raise _invalid("Allocation WorkIntent source is unavailable.")
        return seal_product_preparation_checkpoint(
            {
                "tenant_id": allocation["tenant_id"],
                "checkpoint_id": checkpoint_id,
                "checkpoint_schema_version": (
                    PRODUCT_PREPARATION_CHECKPOINT_SCHEMA_VERSION
                ),
                "checkpoint_version": 1,
                "previous_checkpoint_id": None,
                "previous_checkpoint_hash": None,
                "agent_execution_id": allocation["execution_id"],
                "requester_ref": allocation["subject_id"],
                "work_intent_id": allocation["work_intent_id"],
                "work_intent_revision": int(work_intent["intent_revision"]),
                "work_intent_hash": work_intent["intent_hash"],
                "agent_context_id": agent_context["context_id"],
                "context_generation": int(agent_context["context_generation"]),
                "context_hash": agent_context["context_hash"],
                "business_context_hash": allocation["intent_hash"],
                "capability_id": self.registration.capability_id,
                "capability_version": self.registration.capability_version,
                "capability_release_ref": lock.bundle_manifest_ref,
                "capability_registration_hash": (
                    self.registration.trigger_capability.capability_registration_hash
                ),
                "coordinator_id": self.registration.coordinator_id,
                "coordinator_version": self.registration.coordinator_version,
                "coordinator_registration_hash": self.registration.registration_hash,
                "preparation_adapter_source_identity": (
                    self.registration.preparation_adapter_source_identity
                ),
                "materializer_source_identity": (
                    self.registration.materializer_source_identity
                ),
                "stage": self.registration.ready_state,
                "stage_kind": "READY",
                "authority_refs": [
                    {
                        "kind": "ACCOUNTING_ALLOCATION_WORK_INTENT",
                        "reference": allocation["intent_hash"],
                    }
                ],
                "idempotency_key": (
                    "accounting-allocation-product:" + allocation["replay_identity"]
                ),
                "correlation_id": allocation["execution_id"],
                "causation_id": str(source["source_ref"]),
                "created_at": allocation["requested_at"],
            }
        )


@dataclass(frozen=True)
class InstalledAccountingAllocationProductPlanActivation:
    registration: ProductPlanningCoordinatorRegistration
    activation: Any

    def __post_init__(self) -> None:
        if (
            self.registration.coordinator_id != ACCOUNTING_ALLOCATION_COORDINATOR_ID
            or not callable(getattr(self.activation, "activate", None))
        ):
            raise _invalid("Allocation Product plan activation is unavailable.")

    def activate(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        **_values: Any,
    ) -> Mapping[str, Any]:
        allocation = work_intent.get(ACCOUNTING_ALLOCATION_BINDING_FIELD)
        return self.activation.activate(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
        )


def build_accounting_allocation_activation_documents(
    *,
    product_capabilities: ProductCapabilityRegistry,
) -> tuple[dict[str, Any], dict[str, Any]]:
    active = build_accounting_allocation_product_coordinator_registration(
        product_capabilities=product_capabilities,
        activation_status="ACTIVE",
    )
    contract = build_accounting_allocation_product_coordinator_registration(
        product_capabilities=product_capabilities,
        activation_status="CONTRACT_ONLY",
    )
    rollback = {
        "schema_version": "ae.accounting_allocation_coordinator_rollback.v1",
        "rollback_state": "CONTRACT_ONLY",
        "coordinator_id": contract.coordinator_id,
        "coordinator_version": contract.coordinator_version,
        "coordinator_registration_hash": contract.registration_hash,
        "product_capability_registry_hash": product_capabilities.registry_hash,
        "history_preservation": "PRESERVE_INTENT_CHECKPOINT_PLAN_JOB_RESULT",
        "content_included": False,
        "secret_included": False,
    }
    rollback["content_hash"] = semantic_sha256_hash_ref(rollback)
    activation = {
        "schema_version": "ae.accounting_allocation_coordinator_activation.v1",
        "activation_state": "ACTIVE",
        "coordinator": {
            "coordinator_id": active.coordinator_id,
            "coordinator_version": active.coordinator_version,
            "registration_hash": active.registration_hash,
        },
        "product_capability_registry_hash": product_capabilities.registry_hash,
        "preparation_adapter_source_identity": (
            active.preparation_adapter_source_identity
        ),
        "materializer_source_identity": active.materializer_source_identity,
        "skill_bundle_locks": [
            item.projection() for item in active.installed_skill_bundle_locks
        ],
        "runtime_assignment_handlers": ["EXECUTABLE_STEP"],
        "checkpoint_schema_version": active.checkpoint_schema_version,
        "rollback_receipt_hash": rollback["content_hash"],
        "content_included": False,
        "secret_included": False,
    }
    activation["content_hash"] = semantic_sha256_hash_ref(activation)
    return activation, rollback


def load_accounting_allocation_coordinator_activation(
    *,
    product_capabilities: ProductCapabilityRegistry,
    environ: Mapping[str, str],
) -> AccountingAllocationCoordinatorAdmission:
    activation_path = Path(
        str(
            environ.get("NEX_AE_ACCOUNTING_ALLOCATION_COORDINATOR_ACTIVATION_PATH")
            or DEFAULT_ACCOUNTING_ALLOCATION_ACTIVATION_PATH
        )
    )
    rollback_path = Path(
        str(
            environ.get("NEX_AE_ACCOUNTING_ALLOCATION_COORDINATOR_ROLLBACK_PATH")
            or DEFAULT_ACCOUNTING_ALLOCATION_ROLLBACK_PATH
        )
    )
    activation = _json_object(activation_path)
    rollback = _json_object(rollback_path)
    expected_activation, expected_rollback = (
        build_accounting_allocation_activation_documents(
            product_capabilities=product_capabilities
        )
    )
    if activation != expected_activation:
        raise _invalid("Allocation Product coordinator activation lock has drifted.")
    if rollback != expected_rollback:
        raise _invalid("Allocation Product coordinator rollback receipt has drifted.")
    return AccountingAllocationCoordinatorAdmission(
        registration=build_accounting_allocation_product_coordinator_registration(
            product_capabilities=product_capabilities,
            activation_status="ACTIVE",
        ),
        activation_lock=MappingProxyType(activation),
        rollback_receipt=MappingProxyType(rollback),
    )


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise _invalid(f"{path} must contain a JSON object.")
    return value


def _invalid(detail: str) -> AccountingAllocationProductCoordinatorError:
    return AccountingAllocationProductCoordinatorError(
        "ACCOUNTING_ALLOCATION_PRODUCT_COORDINATOR_INVALID", detail
    )


def _conflict(detail: str) -> AccountingAllocationProductCoordinatorError:
    return AccountingAllocationProductCoordinatorError(
        "ACCOUNTING_ALLOCATION_PRODUCT_COORDINATOR_CONFLICT", detail
    )


__all__ = [
    "ACCOUNTING_ALLOCATION_COORDINATOR_ID",
    "ACCOUNTING_ALLOCATION_COORDINATOR_VERSION",
    "ACCOUNTING_ALLOCATION_READY_STATE",
    "AccountingAllocationCoordinatorAdmission",
    "AccountingAllocationProductCoordinatorError",
    "InstalledAccountingAllocationProductCoordinator",
    "InstalledAccountingAllocationProductPlanActivation",
    "build_accounting_allocation_activation_documents",
    "build_accounting_allocation_product_coordinator_registration",
    "load_accounting_allocation_coordinator_activation",
]
