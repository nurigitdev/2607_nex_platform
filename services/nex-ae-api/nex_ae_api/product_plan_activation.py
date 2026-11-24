from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.m1_plan_activation import (
    AgentExecutionStore,
    AgentPlanStore,
    ExecutablePlanStore,
    PlanValidationStore,
    RuntimeScheduler,
)

PRODUCT_PLAN_ACTIVATION_SCHEMA = "ae.product_plan_activation.v1"


@dataclass
class ProductPlanActivationError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


class InstalledProductPlanActivation:
    """Persist any admitted product plan and enter the common RuntimeJob engine."""

    def __init__(
        self,
        *,
        agent_plans: AgentPlanStore,
        validations: PlanValidationStore,
        executable_plans: ExecutablePlanStore,
        executions: AgentExecutionStore,
        scheduler: RuntimeScheduler,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        for component, method in (
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
                raise _invalid("Product plan activation dependency is unavailable.")
        self._agent_plans = agent_plans
        self._validations = validations
        self._executable_plans = executable_plans
        self._executions = executions
        self._scheduler = scheduler
        self._clock = clock or (lambda: datetime.now(UTC))

    def activate(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        activation_ref: str,
        materialized: Any,
    ) -> dict[str, Any]:
        plan = _mapping(getattr(materialized, "agent_plan", None), "AgentPlan")
        validation = _mapping(
            getattr(materialized, "validation_result", None), "PlanValidation"
        )
        executable = _mapping(
            getattr(materialized, "executable_plan", None), "ExecutablePlan"
        )
        _require_lineage(execution_id, plan, validation, executable)
        created_at = _timestamp(self._clock())
        persisted_plan, plan_replayed = self._persist_plan(tenant_id, plan, created_at)
        persisted_validation, validation_replayed = self._persist_validation(
            tenant_id, execution_id, validation
        )
        persisted_executable, executable_replayed = self._persist_executable(
            tenant_id, executable
        )
        runtime_job = self._scheduler.schedule_next(
            tenant_id=tenant_id,
            execution_id=execution_id,
            now=_text(executable.get("compiled_at"), "compiled_at"),
        )
        result = {
            "schema_version": PRODUCT_PLAN_ACTIVATION_SCHEMA,
            "activation_ref": _text(activation_ref, "activation_ref"),
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
            {k: v for k, v in result.items() if k not in {"runtime_job", "replayed"}}
        )
        return result

    def _persist_plan(
        self, tenant_id: str, desired: Mapping[str, Any], created_at: str
    ) -> tuple[dict[str, Any], bool]:
        existing = self._agent_plans.get(
            tenant_id=tenant_id, agent_plan_id=desired["agent_plan_id"]
        )
        if existing is not None:
            return _exact(existing, desired, "AgentPlan"), True
        saved = self._agent_plans.save(
            tenant_id=tenant_id, agent_plan=desired, created_at=created_at
        )
        return _exact(saved, desired, "AgentPlan"), False

    def _persist_validation(
        self, tenant_id: str, execution_id: str, desired: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        existing = self._validations.get(
            tenant_id=tenant_id,
            validation_result_id=desired["validation_result_id"],
        )
        if existing is not None:
            return _exact(existing, desired, "PlanValidation"), True
        execution = self._executions.get(tenant_id, execution_id)
        if (
            not isinstance(execution, Mapping)
            or execution.get("tenant_id") != tenant_id
            or execution.get("agent_execution_id") != execution_id
            or not isinstance(execution.get("version"), int)
            or isinstance(execution.get("version"), bool)
            or execution["version"] < 1
        ):
            raise _conflict("AgentExecution persistence lineage is unavailable.")
        saved = self._validations.save_and_apply_runtime(
            tenant_id=tenant_id,
            result=desired,
            expected_execution_version=execution["version"],
        )
        return _exact(saved, desired, "PlanValidation"), False

    def _persist_executable(
        self, tenant_id: str, desired: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        existing = self._executable_plans.get(
            tenant_id=tenant_id,
            executable_plan_id=desired["executable_plan_id"],
        )
        if existing is not None:
            return _exact(existing, desired, "ExecutablePlan"), True
        saved = self._executable_plans.save(
            tenant_id=tenant_id, executable_plan=desired
        )
        return _exact(saved, desired, "ExecutablePlan"), False


def _require_lineage(
    execution_id: str,
    plan: Mapping[str, Any],
    validation: Mapping[str, Any],
    executable: Mapping[str, Any],
) -> None:
    validation_plan = validation.get("agent_plan_ref")
    executable_plan = executable.get("agent_plan_ref")
    executable_validation = executable.get("validation_result_ref")
    if (
        plan.get("execution_id") != execution_id
        or validation.get("execution_id") != execution_id
        or executable.get("execution_id") != execution_id
        or validation.get("status") != "VALID"
        or not isinstance(validation_plan, Mapping)
        or validation_plan.get("id") != plan.get("agent_plan_id")
        or validation_plan.get("hash") != plan.get("plan_hash")
        or not isinstance(executable_plan, Mapping)
        or executable_plan.get("id") != plan.get("agent_plan_id")
        or executable_plan.get("hash") != plan.get("plan_hash")
        or not isinstance(executable_validation, Mapping)
        or executable_validation.get("id") != validation.get("validation_result_id")
        or executable_validation.get("hash") != validation.get("result_hash")
    ):
        raise _conflict("Product materialized plan lineage differs.")


def _exact(
    observed: Mapping[str, Any], desired: Mapping[str, Any], label: str
) -> dict[str, Any]:
    if dict(observed) != dict(desired):
        raise _conflict(f"{label} exact replay differs.")
    return dict(observed)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} is unavailable.")
    return dict(value)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("Product plan activation clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise _invalid(f"{field} is invalid.")
    return value.strip()


def _invalid(detail: str) -> ProductPlanActivationError:
    return ProductPlanActivationError("PRODUCT_PLAN_ACTIVATION_INVALID", detail)


def _conflict(detail: str) -> ProductPlanActivationError:
    return ProductPlanActivationError("PRODUCT_PLAN_ACTIVATION_CONFLICT", detail)
