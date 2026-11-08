from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Mapping, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

Json = Mapping[str, Any]

CRON5_RE = re.compile(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$")
FIXED_INTERVAL_RE = re.compile(r"^(?:P[1-9][0-9]*D|PT(?=.*[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)$")

class StaleScheduleVersion(RuntimeError): ...
class DisabledSchedule(RuntimeError): ...
class MaterializationConflict(RuntimeError): ...
class InvalidProjectBinding(ValueError): ...
class InvalidScheduleTimeSemantics(ValueError): ...

@dataclass(frozen=True)
class DueSchedule:
    tenant_id: str
    schedule_id: str
    schedule_version: int
    nominal_time: str  # RFC3339 UTC instant

@dataclass(frozen=True)
class ScheduledWorkMaterializationRequest:
    tenant_id: str
    schedule_id: str
    occurrence_id: str
    nominal_time: str
    expected_schedule_version: int
    materialization_key: str
    work_item_payload_hash: str
    service_authorization_decision_ref: str
    correlation_id: str
    work_item_request: Json

@dataclass(frozen=True)
class ScheduledWorkMaterializationResult:
    tenant_id: str
    schedule_id: str
    occurrence_id: str
    schedule_version: int
    materialization_key: str
    work_item_payload_hash: str
    work_item_id: str
    outcome: str  # CREATED | REUSED_EXISTING

class ScheduleRepository(Protocol):
    def get(self, tenant_id: str, schedule_id: str) -> Json: ...
    def list_due(self, now_utc: str, limit: int = 100) -> list[DueSchedule]: ...
    def try_lease(self, tenant_id: str, schedule_id: str, expected_version: int, worker_ref: str) -> bool: ...
    def get_current_for_update(self, tenant_id: str, schedule_id: str) -> Json: ...
    def update_next_run(self, tenant_id: str, schedule_id: str, expected_version: int, last_run_at: str, next_run_at: str) -> None: ...

class ScheduleOccurrenceRepository(Protocol):
    def create_or_get(self, tenant_id: str, schedule_id: str, schedule_version: int, nominal_time: str, materialization_key: str) -> Json: ...
    def mark_skipped(self, tenant_id: str, occurrence_id: str, reason: str) -> None: ...
    def mark_failed(self, tenant_id: str, occurrence_id: str, failure_ref: str) -> None: ...

class ScheduledWorkMaterializer(Protocol):
    def materialize_atomic(self, request: ScheduledWorkMaterializationRequest) -> ScheduledWorkMaterializationResult:
        """Single WC transaction boundary.

        REQUIRED semantics:
        1) Lock current ScheduleSpec and verify enabled=true and version==expected_schedule_version.
        2) Verify service/current authorization and tenant/project scope.
        3) Verify WorkItem.source_type=SCHEDULE and source_ref==occurrence_id.
        4) Copy ScheduleTarget.required_capability to WorkItem.routing_target.required_capability.
        5) For PA, require ScheduleSpec.project_id, target.project_scope_ref,
           WorkItem.project_ref.entity_id and WorkItem.routing_target.project_scope_ref to bind the same project.
        6) Insert/get wc_schedule_materialization and WorkItem in one transaction.
           Same occurrence/key + same payload hash returns the existing WorkItem.
           Same occurrence/key + different payload hash raises MATERIALIZATION_CONFLICT.
        7) Mark ScheduleOccurrence MATERIALIZED with that WorkItem before commit.
        8) Never create AgentExecution here; execution starts only after successful WC atomic Claim.
        """
        ...

class ScheduleAuditRepository(Protocol):
    def append(self, event: Json) -> None: ...


def validate_iana_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidScheduleTimeSemantics(f"unknown IANA timezone: {timezone_name}") from exc


def validate_expression(expression_type: str, profile: str, expression: str) -> None:
    if expression_type == 'CRON':
        if profile != 'CRON5_V1' or not CRON5_RE.fullmatch(expression):
            raise InvalidScheduleTimeSemantics('CRON requires CRON5_V1 and exactly five fields')
        return
    if expression_type == 'FIXED_INTERVAL':
        if profile != 'ISO8601_INTERVAL_V1' or not FIXED_INTERVAL_RE.fullmatch(expression):
            raise InvalidScheduleTimeSemantics('FIXED_INTERVAL requires canonical ISO8601_INTERVAL_V1')
        return
    raise InvalidScheduleTimeSemantics(f'unsupported expression type: {expression_type}')


def validate_pa_project_binding(schedule: Json, work_item: Json | None = None) -> None:
    target = schedule.get('target') or {}
    if target.get('required_agent_type') != 'PA':
        return
    project_id = schedule.get('project_id')
    scope = target.get('project_scope_ref')
    if not project_id or not scope or project_id != scope:
        raise InvalidProjectBinding('PA schedule requires project_id == target.project_scope_ref')
    if work_item is not None:
        routing = work_item.get('routing_target') or {}
        project_ref = work_item.get('project_ref') or {}
        if routing.get('project_scope_ref') != project_id or project_ref.get('entity_type') != 'PROJECT' or project_ref.get('entity_id') != project_id:
            raise InvalidProjectBinding('scheduled PA WorkItem must preserve the same project binding')

# Canonical time semantics WC_SCHEDULE_TIME_V1:
# - CRON5_V1 has five fields (minute hour day-of-month month day-of-week), no seconds field.
# - CRON is evaluated in the ScheduleSpec IANA timezone.
# - nonexistent DST local time: SKIP_NONEXISTENT_LOCAL_TIME.
# - overlapping DST local time: EARLIEST_OFFSET_ONLY, yielding one nominal occurrence.
# - FIXED_INTERVAL is instant-based using ISO8601_INTERVAL_V1.
# - nominal_time / last_run_at / next_run_at are persisted as RFC3339 UTC instants.
# - Misfire is applied to the deterministic set of nominal UTC instants: SKIP / bounded CATCH_UP / LATEST_ONLY.
