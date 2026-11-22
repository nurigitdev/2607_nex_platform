from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.m1_product_planning_coordinator import (
    M1_PLAN_MATERIALIZER_SOURCE_IDENTITY,
)
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistration,
)
from nex_ae_api.product_planning_proposals import (
    validate_product_planning_proposal_reference,
)

M1_PLAN_ACTIVATION_SCHEMA_VERSION = "ae.m1_plan_activation.v1"


@dataclass
class M1PlanActivationError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class M1ReadyCheckpointSource(Protocol):
    registration: ProductPlanningCoordinatorRegistration

    def load_ready_checkpoint(self, **values: Any) -> Mapping[str, Any]: ...


class M1PlanMaterializer(Protocol):
    def materialize_transaction_plan(self, **values: Any) -> Any: ...


class AgentPlanStore(Protocol):
    def get(
        self, *, tenant_id: str, agent_plan_id: str
    ) -> Mapping[str, Any] | None: ...

    def save(self, **values: Any) -> Mapping[str, Any]: ...


class PlanValidationStore(Protocol):
    def get(
        self, *, tenant_id: str, validation_result_id: str
    ) -> Mapping[str, Any] | None: ...

    def save_and_apply_runtime(self, **values: Any) -> Mapping[str, Any]: ...


class ExecutablePlanStore(Protocol):
    def get(
        self, *, tenant_id: str, executable_plan_id: str
    ) -> Mapping[str, Any] | None: ...

    def save(self, **values: Any) -> Mapping[str, Any]: ...


class AgentExecutionStore(Protocol):
    def get(
        self, tenant_id: str, agent_execution_id: str
    ) -> Mapping[str, Any] | None: ...


class RuntimeScheduler(Protocol):
    def schedule_next(self, **values: Any) -> Mapping[str, Any] | None: ...


class InstalledM1PlanActivation:
    """Persist a READY_FOR_D04 deterministic plan before scheduling it."""

    def __init__(
        self,
        *,
        registration: ProductPlanningCoordinatorRegistration,
        ready_checkpoints: M1ReadyCheckpointSource,
        materializer: M1PlanMaterializer,
        agent_plans: AgentPlanStore,
        validations: PlanValidationStore,
        executable_plans: ExecutablePlanStore,
        executions: AgentExecutionStore,
        scheduler: RuntimeScheduler,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            ready_checkpoints.registration != registration
            or registration.materializer_source_identity
            != M1_PLAN_MATERIALIZER_SOURCE_IDENTITY
        ):
            raise _invalid("M1 plan activation registration is invalid.")
        for component, method in (
            (materializer, "materialize_transaction_plan"),
            (agent_plans, "get"),
            (agent_plans, "save"),
            (validations, "get"),
            (validations, "save_and_apply_runtime"),
            (executable_plans, "get"),
            (executable_plans, "save"),
            (executions, "get"),
            (scheduler, "schedule_next"),
        ):
            if not callable(getattr(component, method, None)):
                raise _invalid("M1 plan activation dependency is unavailable.")
        self.registration = registration
        self._ready_checkpoints = ready_checkpoints
        self._materializer = materializer
        self._agent_plans = agent_plans
        self._validations = validations
        self._executable_plans = executable_plans
        self._executions = executions
        self._scheduler = scheduler
        self._clock = clock or (lambda: datetime.now(UTC))

    def activate(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        execution: Mapping[str, Any],
    ) -> dict[str, Any]:
        ready = self._ready_checkpoints.load_ready_checkpoint(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            execution=execution,
        )
        checkpoint = _mapping(ready.get("checkpoint"), "READY checkpoint")
        preparation = _mapping(ready.get("preparation"), "M1 preparation")
        proposal_ref = ready.get("planning_proposal_ref")
        if proposal_ref is not None:
            try:
                proposal_ref = validate_product_planning_proposal_reference(
                    proposal_ref
                )
            except ValueError as exc:
                raise _conflict(
                    "M1 Product planning proposal reference differs."
                ) from exc
        if (
            self.registration.planning_policy.mode == "PROVIDER_ASSISTED_REQUIRED"
            and proposal_ref is None
        ):
            raise _conflict("M1 Product planning proposal reference is unavailable.")
        if (
            checkpoint.get("stage") != self.registration.ready_state
            or checkpoint.get("stage_kind") != "READY"
            or checkpoint.get("materializer_source_identity")
            != self.registration.materializer_source_identity
            or preparation.get("stage") != self.registration.ready_state
            or checkpoint.get("business_context_hash")
            != preparation.get("business_context_hash")
        ):
            raise _conflict("M1 READY_FOR_D04 checkpoint lineage differs.")

        materialized = self._materializer.materialize_transaction_plan(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            preparation_checkpoint=preparation,
            product_planning_proposal_ref=proposal_ref,
        )
        agent_plan = _mapping(getattr(materialized, "agent_plan", None), "M1 AgentPlan")
        validation = _mapping(
            getattr(materialized, "validation_result", None),
            "M1 PlanValidation",
        )
        executable_plan = _mapping(
            getattr(materialized, "executable_plan", None),
            "M1 ExecutablePlan",
        )
        tenant_id = _text(checkpoint.get("tenant_id"), "tenant_id", 128)
        execution_id = _text(
            checkpoint.get("agent_execution_id"), "agent_execution_id", 64
        )
        _require_materialized_lineage(
            execution_id=execution_id,
            agent_plan=agent_plan,
            validation=validation,
            executable_plan=executable_plan,
        )

        persisted_plan, plan_replayed = self._persist_agent_plan(
            tenant_id=tenant_id,
            desired=agent_plan,
            created_at=_timestamp(self._clock()),
        )
        persisted_validation, validation_replayed = self._persist_validation(
            tenant_id=tenant_id,
            execution_id=execution_id,
            desired=validation,
        )
        persisted_executable, executable_replayed = self._persist_executable_plan(
            tenant_id=tenant_id,
            desired=executable_plan,
        )

        runtime_job = self._scheduler.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution_id,
            now=_timestamp(self._clock()),
        )
        result = {
            "schema_version": M1_PLAN_ACTIVATION_SCHEMA_VERSION,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
            "agent_plan_id": persisted_plan["agent_plan_id"],
            "agent_plan_hash": persisted_plan["plan_hash"],
            "validation_result_id": persisted_validation["validation_result_id"],
            "validation_result_hash": persisted_validation["result_hash"],
            "executable_plan_id": persisted_executable["executable_plan_id"],
            "executable_plan_hash": persisted_executable["executable_plan_hash"],
            "runtime_job": None if runtime_job is None else dict(runtime_job),
            "replayed": {
                "agent_plan": plan_replayed,
                "validation": validation_replayed,
                "executable_plan": executable_replayed,
            },
        }
        result["activation_hash"] = semantic_sha256_hash_ref(
            {
                key: value
                for key, value in result.items()
                if key not in {"runtime_job", "replayed"}
            }
        )
        return result

    def _persist_agent_plan(
        self, *, tenant_id: str, desired: Mapping[str, Any], created_at: str
    ) -> tuple[dict[str, Any], bool]:
        existing = self._agent_plans.get(
            tenant_id=tenant_id,
            agent_plan_id=_text(desired.get("agent_plan_id"), "agent_plan_id", 64),
        )
        if existing is not None:
            return _require_exact(existing, desired, "M1 AgentPlan"), True
        saved = self._agent_plans.save(
            tenant_id=tenant_id,
            agent_plan=desired,
            created_at=created_at,
        )
        return _require_exact(saved, desired, "M1 AgentPlan"), False

    def _persist_validation(
        self, *, tenant_id: str, execution_id: str, desired: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        identity = _text(
            desired.get("validation_result_id"), "validation_result_id", 64
        )
        existing = self._validations.get(
            tenant_id=tenant_id,
            validation_result_id=identity,
        )
        if existing is not None:
            return _require_exact(existing, desired, "M1 PlanValidation"), True
        execution = self._executions.get(tenant_id, execution_id)
        if (
            not isinstance(execution, Mapping)
            or execution.get("tenant_id") != tenant_id
            or execution.get("agent_execution_id") != execution_id
        ):
            raise _conflict("M1 AgentExecution persistence lineage is unavailable.")
        version = execution.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise _conflict("M1 AgentExecution version is invalid.")
        saved = self._validations.save_and_apply_runtime(
            tenant_id=tenant_id,
            result=desired,
            expected_execution_version=version,
        )
        return _require_exact(saved, desired, "M1 PlanValidation"), False

    def _persist_executable_plan(
        self, *, tenant_id: str, desired: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        identity = _text(desired.get("executable_plan_id"), "executable_plan_id", 64)
        existing = self._executable_plans.get(
            tenant_id=tenant_id,
            executable_plan_id=identity,
        )
        if existing is not None:
            return _require_exact(existing, desired, "M1 ExecutablePlan"), True
        saved = self._executable_plans.save(
            tenant_id=tenant_id,
            executable_plan=desired,
        )
        return _require_exact(saved, desired, "M1 ExecutablePlan"), False


def _require_materialized_lineage(
    *,
    execution_id: str,
    agent_plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    executable_plan: Mapping[str, Any],
) -> None:
    executable_plan_ref = executable_plan.get("agent_plan_ref")
    executable_validation_ref = executable_plan.get("validation_result_ref")
    if (
        agent_plan.get("execution_id") != execution_id
        or validation.get("execution_id") != execution_id
        or executable_plan.get("execution_id") != execution_id
        or validation.get("status") != "VALID"
        or not isinstance(validation.get("agent_plan_ref"), Mapping)
        or validation["agent_plan_ref"].get("id") != agent_plan.get("agent_plan_id")
        or validation["agent_plan_ref"].get("hash") != agent_plan.get("plan_hash")
        or not isinstance(executable_plan_ref, Mapping)
        or executable_plan_ref.get("id") != agent_plan.get("agent_plan_id")
        or executable_plan_ref.get("hash") != agent_plan.get("plan_hash")
        or not isinstance(executable_validation_ref, Mapping)
        or executable_validation_ref.get("id") != validation.get("validation_result_id")
        or executable_validation_ref.get("hash") != validation.get("result_hash")
    ):
        raise _conflict("M1 materialized plan lineage differs.")


def _require_exact(
    observed: Mapping[str, Any], desired: Mapping[str, Any], label: str
) -> dict[str, Any]:
    if dict(observed) != dict(desired):
        raise _conflict(f"{label} exact replay differs.")
    return dict(observed)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} is unavailable.")
    return dict(value)


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} is invalid.")
    return value.strip()


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("M1 plan activation clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> M1PlanActivationError:
    return M1PlanActivationError("M1_PLAN_ACTIVATION_INVALID", detail)


def _conflict(detail: str) -> M1PlanActivationError:
    return M1PlanActivationError("M1_PLAN_ACTIVATION_CONFLICT", detail)
