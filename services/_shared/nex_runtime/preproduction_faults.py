from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Any


FAULT_PLAN_SCHEMA_VERSION = "preproduction_fault_plan.v1"
FAULT_REHEARSAL_SCHEMA_VERSION = "preproduction_fault_rehearsal.v1"
FAULT_CLASSES = frozenset(
    {
        "service_restart",
        "database_connection_loss",
        "object_storage_degradation",
        "provider_degradation",
        "edge_or_trust_degradation",
    }
)
ALLOWED_MODES = {
    "service_restart": frozenset({"compose_service_restart"}),
    "database_connection_loss": frozenset({"client_connection_block"}),
    "object_storage_degradation": frozenset({"client_route_error"}),
    "provider_degradation": frozenset(
        {"client_timeout", "client_5xx", "client_latency"}
    ),
    "edge_or_trust_degradation": frozenset({"staging_route_block"}),
}
ALLOWED_TARGETS = frozenset(
    {
        "nex-oa",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ag",
        "postgres-route",
        "rustfs-route",
        "embedding-route",
        "reranking-route",
        "generation-route",
        "traefik-route",
        "openbao-route",
    }
)
REQUIRED_PLAN_TARGETS = frozenset(
    {
        "nex-oa",
        "postgres-route",
        "rustfs-route",
        "embedding-route",
        "reranking-route",
        "generation-route",
        "traefik-route",
        "openbao-route",
    }
)
STATES = frozenset(
    {"PLANNED", "INJECTING", "DEGRADED", "RECOVERING", "RECOVERED", "FAILED"}
)
TRANSITIONS = {
    ("PLANNED", "begin_injection"): "INJECTING",
    ("INJECTING", "degradation_observed"): "DEGRADED",
    ("DEGRADED", "begin_recovery"): "RECOVERING",
    ("RECOVERING", "recovery_verified"): "RECOVERED",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SAFE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class FaultPlanError(ValueError):
    pass


@dataclass(frozen=True)
class FaultScenario:
    scenario_id: str
    fault_class: str
    target_alias: str
    injection_mode: str
    maximum_fault_seconds: int
    maximum_detection_ms: int
    maximum_recovery_ms: int
    destructive: bool = False
    provider_process_mutation: bool = False


@dataclass(frozen=True)
class FaultState:
    scenario_id: str
    state: str = "PLANNED"
    revision: int = 0
    changed_at_ms: int = 0
    failure_code: str | None = None


@dataclass(frozen=True)
class FaultRehearsalResult:
    scenario_id: str
    final_state: str
    detection_ms: int
    recovery_ms: int
    data_loss_count: int = 0
    isolation_violation_count: int = 0
    residue_count: int = 0


def build_default_fault_plan(
    *,
    release_candidate_id: str,
    workload_digest: str,
) -> dict[str, Any]:
    _safe_id(release_candidate_id, "release_candidate_id")
    if SAFE_DIGEST.fullmatch(workload_digest) is None:
        raise FaultPlanError("workload_digest is invalid")
    scenarios = (
        FaultScenario("fault:oa-restart", "service_restart", "nex-oa", "compose_service_restart", 30, 2_000, 30_000),
        FaultScenario("fault:database-route", "database_connection_loss", "postgres-route", "client_connection_block", 15, 1_000, 15_000),
        FaultScenario("fault:rustfs-route", "object_storage_degradation", "rustfs-route", "client_route_error", 15, 1_000, 15_000),
        FaultScenario("fault:embedding-timeout", "provider_degradation", "embedding-route", "client_timeout", 15, 1_000, 30_000),
        FaultScenario("fault:reranking-error", "provider_degradation", "reranking-route", "client_5xx", 15, 1_000, 30_000),
        FaultScenario("fault:generation-latency", "provider_degradation", "generation-route", "client_latency", 30, 2_000, 60_000),
        FaultScenario("fault:edge-route", "edge_or_trust_degradation", "traefik-route", "staging_route_block", 15, 1_000, 30_000),
        FaultScenario("fault:trust-route", "edge_or_trust_degradation", "openbao-route", "staging_route_block", 15, 1_000, 30_000),
    )
    return validate_fault_plan(
        {
            "fault_plan_schema_version": FAULT_PLAN_SCHEMA_VERSION,
            "release_candidate_id": release_candidate_id,
            "workload_digest": workload_digest,
            "topology": "single_host_docker_compose",
            "scenarios": [asdict(item) for item in scenarios],
            "production_targeted": False,
        }
    )


def validate_fault_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if plan.get("fault_plan_schema_version") != FAULT_PLAN_SCHEMA_VERSION:
        raise FaultPlanError("fault plan schema is invalid")
    release_candidate_id = _safe_id(plan.get("release_candidate_id"), "release_candidate_id")
    workload_digest = str(plan.get("workload_digest") or "")
    if SAFE_DIGEST.fullmatch(workload_digest) is None:
        raise FaultPlanError("workload_digest is invalid")
    if plan.get("topology") != "single_host_docker_compose":
        raise FaultPlanError("fault plan topology is invalid")
    if plan.get("production_targeted") is not False:
        raise FaultPlanError("production fault injection is forbidden")
    raw_scenarios = plan.get("scenarios")
    if not isinstance(raw_scenarios, Sequence) or isinstance(raw_scenarios, (str, bytes)):
        raise FaultPlanError("fault scenarios are required")
    scenarios = [_normalize_scenario(item) for item in raw_scenarios]
    if not scenarios:
        raise FaultPlanError("fault scenarios are required")
    scenario_ids = [item.scenario_id for item in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise FaultPlanError("fault scenario IDs must be unique")
    if {item.fault_class for item in scenarios} != FAULT_CLASSES:
        raise FaultPlanError("fault plan must cover every required class")
    if {item.target_alias for item in scenarios} != REQUIRED_PLAN_TARGETS:
        raise FaultPlanError("fault plan target inventory is incomplete")
    payload = {
        "fault_plan_schema_version": FAULT_PLAN_SCHEMA_VERSION,
        "release_candidate_id": release_candidate_id,
        "workload_digest": workload_digest,
        "topology": "single_host_docker_compose",
        "scenarios": [asdict(item) for item in scenarios],
        "production_targeted": False,
    }
    return {**payload, "fault_plan_digest": _digest(payload), "admission": "ADMITTED"}


def transition_fault_state(
    current: FaultState,
    event: str,
    *,
    changed_at_ms: int,
    failure_code: str | None = None,
) -> FaultState:
    if current.state not in STATES:
        raise FaultPlanError("fault state is invalid")
    if (
        not isinstance(changed_at_ms, int)
        or isinstance(changed_at_ms, bool)
        or changed_at_ms <= current.changed_at_ms
    ):
        raise FaultPlanError("fault transition time must increase")
    if event == "fail":
        if current.state in {"RECOVERED", "FAILED"}:
            raise FaultPlanError("terminal fault state cannot transition")
        code = _safe_id(failure_code, "failure_code")
        return replace(
            current,
            state="FAILED",
            revision=current.revision + 1,
            changed_at_ms=changed_at_ms,
            failure_code=code,
        )
    next_state = TRANSITIONS.get((current.state, event))
    if next_state is None:
        raise FaultPlanError("fault state transition is not allowed")
    if failure_code is not None:
        raise FaultPlanError("successful transitions cannot carry failure_code")
    return replace(
        current,
        state=next_state,
        revision=current.revision + 1,
        changed_at_ms=changed_at_ms,
    )


def evaluate_fault_rehearsals(
    admitted_plan: Mapping[str, Any],
    results: Sequence[FaultRehearsalResult],
) -> dict[str, Any]:
    if admitted_plan.get("admission") != "ADMITTED" or not SAFE_DIGEST.fullmatch(
        str(admitted_plan.get("fault_plan_digest") or "")
    ):
        raise FaultPlanError("an admitted fault plan is required")
    scenarios = {
        str(item["scenario_id"]): item for item in admitted_plan.get("scenarios", [])
    }
    if not results:
        raise FaultPlanError("fault rehearsal results are required")
    result_ids = [item.scenario_id for item in results]
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(scenarios):
        raise FaultPlanError("fault rehearsal inventory must exactly match the plan")
    for item in results:
        _validate_rehearsal_result(item)
    checks = {
        "all_scenarios_recovered": all(item.final_state == "RECOVERED" for item in results),
        "detection_budget_satisfied": all(
            item.detection_ms <= int(scenarios[item.scenario_id]["maximum_detection_ms"])
            for item in results
        ),
        "recovery_budget_satisfied": all(
            item.recovery_ms <= int(scenarios[item.scenario_id]["maximum_recovery_ms"])
            for item in results
        ),
        "zero_data_loss": sum(item.data_loss_count for item in results) == 0,
        "zero_isolation_violations": sum(
            item.isolation_violation_count for item in results
        ) == 0,
        "zero_residue": sum(item.residue_count for item in results) == 0,
        "provider_processes_not_mutated": all(
            item.get("provider_process_mutation") is False
            for item in admitted_plan["scenarios"]
            if item["fault_class"] == "provider_degradation"
        ),
        "production_not_targeted": admitted_plan.get("production_targeted") is False,
    }
    passed = all(checks.values())
    return {
        "rehearsal_schema_version": FAULT_REHEARSAL_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "fault_plan_digest": admitted_plan["fault_plan_digest"],
        "checks": checks,
        "failed_checks": sorted(name for name, value in checks.items() if not value),
        "summary": {
            "scenario_count": len(results),
            "recovered_count": sum(item.final_state == "RECOVERED" for item in results),
            "fault_class_count": len({scenarios[item.scenario_id]["fault_class"] for item in results}),
            "maximum_detection_ms": max(item.detection_ms for item in results),
            "maximum_recovery_ms": max(item.recovery_ms for item in results),
            "residue_count": sum(item.residue_count for item in results),
        },
    }


def _normalize_scenario(value: object) -> FaultScenario:
    if not isinstance(value, Mapping):
        raise FaultPlanError("fault scenario is invalid")
    try:
        scenario = FaultScenario(**dict(value))
    except (TypeError, ValueError) as exc:
        raise FaultPlanError("fault scenario shape is invalid") from exc
    _safe_id(scenario.scenario_id, "scenario_id")
    if scenario.fault_class not in FAULT_CLASSES:
        raise FaultPlanError("fault class is invalid")
    if scenario.target_alias not in ALLOWED_TARGETS:
        raise FaultPlanError("fault target alias is not allowlisted")
    if scenario.injection_mode not in ALLOWED_MODES[scenario.fault_class]:
        raise FaultPlanError("fault injection mode is invalid")
    for name, value, maximum in (
        ("maximum_fault_seconds", scenario.maximum_fault_seconds, 300),
        ("maximum_detection_ms", scenario.maximum_detection_ms, 60_000),
        ("maximum_recovery_ms", scenario.maximum_recovery_ms, 600_000),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            or value > maximum
        ):
            raise FaultPlanError(f"{name} is outside the allowed range")
    if scenario.destructive or scenario.provider_process_mutation:
        raise FaultPlanError("destructive or provider-process mutation is forbidden")
    return scenario


def _validate_rehearsal_result(result: FaultRehearsalResult) -> None:
    _safe_id(result.scenario_id, "scenario_id")
    if result.final_state not in STATES:
        raise FaultPlanError("rehearsal final state is invalid")
    values = (
        result.detection_ms,
        result.recovery_ms,
        result.data_loss_count,
        result.isolation_violation_count,
        result.residue_count,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in values
    ):
        raise FaultPlanError("rehearsal measurements must be non-negative integers")


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise FaultPlanError(f"{field} is invalid")
    return value


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
