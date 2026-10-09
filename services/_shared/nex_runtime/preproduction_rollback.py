from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Any


ROLLBACK_PLAN_SCHEMA_VERSION = "preproduction_rollback_plan.v1"
ROLLBACK_EVALUATION_SCHEMA_VERSION = "preproduction_rollback_evaluation.v1"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
STATES = frozenset({"PLANNED", "TRIGGERED", "RESTORING", "VERIFYING", "COMPLETED", "FAILED"})
TRANSITIONS = {
    ("PLANNED", "trigger"): "TRIGGERED",
    ("TRIGGERED", "begin_restore"): "RESTORING",
    ("RESTORING", "begin_verification"): "VERIFYING",
    ("VERIFYING", "verification_passed"): "COMPLETED",
}
REQUIRED_COMPONENTS = (
    "application_release_set",
    "runtime_configuration",
    "database_schema_compatibility",
    "model_alias_calibration",
    "private_storage_routing",
    "trust_tls_generation",
)


class RollbackPlanError(ValueError):
    pass


@dataclass(frozen=True)
class RollbackComponent:
    component_id: str
    candidate_digest: str
    last_known_good_digest: str
    strategy: str
    preserves_committed_data: bool = True


@dataclass(frozen=True)
class RollbackState:
    rollback_id: str
    state: str = "PLANNED"
    revision: int = 0
    changed_at_ms: int = 0
    failure_code: str | None = None


@dataclass(frozen=True)
class RollbackComponentResult:
    component_id: str
    restored_digest: str
    verification_passed: bool
    committed_data_loss_count: int = 0


@dataclass(frozen=True)
class RollbackResidue:
    database_row_count: int = 0
    object_version_count: int = 0
    active_job_count: int = 0
    lease_count: int = 0
    process_count: int = 0
    route_override_count: int = 0


def build_default_rollback_plan(
    *,
    release_candidate_id: str,
    fault_plan_digest: str,
) -> dict[str, Any]:
    _safe_id(release_candidate_id, "release_candidate_id")
    _safe_digest(fault_plan_digest, "fault_plan_digest")
    components = tuple(
        RollbackComponent(
            component_id=component_id,
            candidate_digest=_seed_digest(f"candidate:{component_id}"),
            last_known_good_digest=_seed_digest(f"lkg:{component_id}"),
            strategy=(
                "compatibility_hold"
                if component_id == "database_schema_compatibility"
                else "atomic_reference_restore"
            ),
        )
        for component_id in REQUIRED_COMPONENTS
    )
    return validate_rollback_plan(
        {
            "rollback_plan_schema_version": ROLLBACK_PLAN_SCHEMA_VERSION,
            "release_candidate_id": release_candidate_id,
            "fault_plan_digest": fault_plan_digest,
            "topology": "single_host_docker_compose",
            "maximum_recovery_ms": 300_000,
            "components": [asdict(item) for item in components],
            "production_deployment_targeted": False,
        }
    )


def validate_rollback_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("rollback_plan_schema_version") != ROLLBACK_PLAN_SCHEMA_VERSION:
        raise RollbackPlanError("rollback plan schema is invalid")
    release_candidate_id = _safe_id(plan.get("release_candidate_id"), "release_candidate_id")
    fault_plan_digest = _safe_digest(plan.get("fault_plan_digest"), "fault_plan_digest")
    if plan.get("topology") != "single_host_docker_compose":
        raise RollbackPlanError("rollback topology is invalid")
    if plan.get("production_deployment_targeted") is not False:
        raise RollbackPlanError("production rollback rehearsal is forbidden")
    maximum_recovery_ms = plan.get("maximum_recovery_ms")
    if (
        not isinstance(maximum_recovery_ms, int)
        or isinstance(maximum_recovery_ms, bool)
        or not 1_000 <= maximum_recovery_ms <= 3_600_000
    ):
        raise RollbackPlanError("maximum_recovery_ms is outside the allowed range")
    raw_components = plan.get("components")
    if not isinstance(raw_components, Sequence) or isinstance(raw_components, (str, bytes)):
        raise RollbackPlanError("rollback components are required")
    components = [_normalize_component(item) for item in raw_components]
    ids = [item.component_id for item in components]
    if len(ids) != len(set(ids)) or set(ids) != set(REQUIRED_COMPONENTS):
        raise RollbackPlanError("rollback component inventory must be exact and unique")
    payload = {
        "rollback_plan_schema_version": ROLLBACK_PLAN_SCHEMA_VERSION,
        "release_candidate_id": release_candidate_id,
        "fault_plan_digest": fault_plan_digest,
        "topology": "single_host_docker_compose",
        "maximum_recovery_ms": maximum_recovery_ms,
        "components": [asdict(item) for item in components],
        "production_deployment_targeted": False,
    }
    return {**payload, "rollback_plan_digest": _digest(payload), "admission": "ADMITTED"}


def transition_rollback_state(
    current: RollbackState,
    event: str,
    *,
    changed_at_ms: int,
    failure_code: str | None = None,
) -> RollbackState:
    if current.state not in STATES:
        raise RollbackPlanError("rollback state is invalid")
    if (
        not isinstance(changed_at_ms, int)
        or isinstance(changed_at_ms, bool)
        or changed_at_ms <= current.changed_at_ms
    ):
        raise RollbackPlanError("rollback transition time must increase")
    if event == "fail":
        if current.state in {"COMPLETED", "FAILED"}:
            raise RollbackPlanError("terminal rollback state cannot transition")
        return replace(
            current,
            state="FAILED",
            revision=current.revision + 1,
            changed_at_ms=changed_at_ms,
            failure_code=_safe_id(failure_code, "failure_code"),
        )
    next_state = TRANSITIONS.get((current.state, event))
    if next_state is None:
        raise RollbackPlanError("rollback transition is not allowed")
    if failure_code is not None:
        raise RollbackPlanError("successful rollback transition cannot carry failure_code")
    return replace(
        current,
        state=next_state,
        revision=current.revision + 1,
        changed_at_ms=changed_at_ms,
    )


def evaluate_rollback_rehearsal(
    admitted_plan: Mapping[str, Any],
    *,
    final_state: RollbackState,
    component_results: Sequence[RollbackComponentResult],
    recovery_ms: int,
    residue: RollbackResidue,
) -> dict[str, Any]:
    if admitted_plan.get("admission") != "ADMITTED" or not SAFE_DIGEST.fullmatch(
        str(admitted_plan.get("rollback_plan_digest") or "")
    ):
        raise RollbackPlanError("an admitted rollback plan is required")
    if final_state.state not in STATES:
        raise RollbackPlanError("rollback final state is invalid")
    if not isinstance(recovery_ms, int) or isinstance(recovery_ms, bool) or recovery_ms < 0:
        raise RollbackPlanError("recovery_ms is invalid")
    _validate_residue(residue)
    expected = {
        str(item["component_id"]): item for item in admitted_plan["components"]
    }
    if not component_results:
        raise RollbackPlanError("rollback component results are required")
    for item in component_results:
        _validate_component_result(item)
    ids = [item.component_id for item in component_results]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise RollbackPlanError("rollback result inventory must be exact and unique")
    residue_count = sum(asdict(residue).values())
    checks = {
        "state_completed": final_state.state == "COMPLETED",
        "all_components_verified": all(item.verification_passed for item in component_results),
        "last_known_good_exact": all(
            item.restored_digest == expected[item.component_id]["last_known_good_digest"]
            for item in component_results
        ),
        "recovery_budget_satisfied": recovery_ms
        <= int(admitted_plan["maximum_recovery_ms"]),
        "committed_data_preserved": sum(
            item.committed_data_loss_count for item in component_results
        )
        == 0,
        "zero_residue": residue_count == 0,
        "production_not_targeted": admitted_plan.get("production_deployment_targeted") is False,
    }
    passed = all(checks.values())
    return {
        "evaluation_schema_version": ROLLBACK_EVALUATION_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "rollback_plan_digest": admitted_plan["rollback_plan_digest"],
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "summary": {
            "component_count": len(component_results),
            "verified_component_count": sum(
                item.verification_passed for item in component_results
            ),
            "recovery_ms": recovery_ms,
            "committed_data_loss_count": sum(
                item.committed_data_loss_count for item in component_results
            ),
            "residue_count": residue_count,
        },
    }


def _normalize_component(value: object) -> RollbackComponent:
    if not isinstance(value, Mapping):
        raise RollbackPlanError("rollback component is invalid")
    try:
        item = RollbackComponent(**dict(value))
    except (TypeError, ValueError) as exc:
        raise RollbackPlanError("rollback component shape is invalid") from exc
    _safe_id(item.component_id, "component_id")
    _safe_digest(item.candidate_digest, "candidate_digest")
    _safe_digest(item.last_known_good_digest, "last_known_good_digest")
    if item.candidate_digest == item.last_known_good_digest:
        raise RollbackPlanError("candidate and last-known-good digests must differ")
    if item.strategy not in {"atomic_reference_restore", "compatibility_hold"}:
        raise RollbackPlanError("rollback strategy is invalid")
    if item.preserves_committed_data is not True:
        raise RollbackPlanError("rollback must preserve committed data")
    return item


def _validate_component_result(result: RollbackComponentResult) -> None:
    if not isinstance(result, RollbackComponentResult):
        raise RollbackPlanError("rollback component result is invalid")
    _safe_id(result.component_id, "component_id")
    _safe_digest(result.restored_digest, "restored_digest")
    if not isinstance(result.verification_passed, bool):
        raise RollbackPlanError("rollback verification flag is invalid")
    if (
        not isinstance(result.committed_data_loss_count, int)
        or isinstance(result.committed_data_loss_count, bool)
        or result.committed_data_loss_count < 0
    ):
        raise RollbackPlanError("committed data loss count is invalid")


def _validate_residue(residue: RollbackResidue) -> None:
    if not isinstance(residue, RollbackResidue) or any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in asdict(residue).values()
    ):
        raise RollbackPlanError("rollback residue counts are invalid")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise RollbackPlanError(f"{field} is invalid")
    return value


def _safe_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or SAFE_DIGEST.fullmatch(value) is None:
        raise RollbackPlanError(f"{field} is invalid")
    return value


def _seed_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
