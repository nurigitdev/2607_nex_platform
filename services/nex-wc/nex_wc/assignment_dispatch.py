from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_runtime import (
    JobQueue,
    JobQueueError,
    ServiceLogEmitter,
    WorkerHeartbeatEmitter,
    WorkerJobExecution,
    WorkerRunnerConfig,
    build_common_job,
    build_job_error,
    build_subject_ref,
    run_worker_once,
    validate_common_job,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

WC_ASSIGNMENT_DISPATCH_JOB_TYPE = "WC_ASSIGNMENT_DISPATCH"
WC_WORK_ITEM_SUBJECT_TYPE = "WC_WORK_ITEM"
ASSIGNMENT_DISPATCH_SCHEMA_VERSION = "wc_assignment_dispatch.v1"

ROUTE = "ROUTE"
CLAIM = "CLAIM"
RECLAIM = "RECLAIM"
ASSIGNMENT_DISPATCH_ACTIONS = frozenset({ROUTE, CLAIM, RECLAIM})
CLAIMABLE_WORK_ITEM_STATES = frozenset({"CREATED", "ROUTED"})
RECOVERABLE_WORK_ITEM_STATE = "ASSIGNED"
ACTION_BY_STATE = {"CREATED": ROUTE, "ROUTED": CLAIM, "ASSIGNED": RECLAIM}

RETRY = "RETRY"
RELOAD = "RELOAD"
TERMINAL = "TERMINAL"
ASSIGNMENT_DISPATCH_DISPOSITIONS = frozenset({RETRY, RELOAD, TERMINAL})

DEFAULT_DISPATCH_MAX_ATTEMPTS = 5
MAX_CLAIMABLE_SCAN_LIMIT = 500
WC_ASSIGNMENT_DISPATCH_WORKER_TYPE = "wc.assignment.dispatch.worker"

NO_ELIGIBLE_AGENT_ERROR = "wc.assignment_no_eligible_agent"
STALE_DISPATCH_ERRORS = frozenset(
    {
        "wc.work_item_route_conflict",
        "wc.work_item_claim_conflict",
        "wc.active_claim_exists",
    }
)


@dataclass(frozen=True)
class AssignmentDispatchContractError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AssignmentDispatchExecutionError(Exception):
    error_code: str
    detail: str
    disposition: str

    def __str__(self) -> str:
        return self.detail


class AssignmentDispatchRepository(Protocol):
    def list_claimable_work_items(
        self,
        *,
        state: str,
        limit: int,
        after: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def list_recoverable_work_items(
        self,
        *,
        observed_at: str,
        limit: int,
        after: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_work_item(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None: ...

    def get_current_assignment_authority(
        self, *, tenant_id: str, work_item_id: str
    ) -> dict[str, Any] | None: ...


class AssignmentDispatchService(Protocol):
    def route(
        self, *, tenant_id: str, work_item_id: str, expected_version: int
    ) -> dict[str, Any]: ...

    def claim(
        self, *, tenant_id: str, work_item_id: str, expected_version: int
    ) -> dict[str, Any]: ...


def validate_claimable_scan(
    *,
    state: object,
    limit: object,
    after: Mapping[str, Any] | None = None,
) -> tuple[str, int, dict[str, str] | None]:
    normalized_state = _required_string(state, "state")
    if normalized_state not in CLAIMABLE_WORK_ITEM_STATES:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_state_invalid",
            "claimable scan state must be CREATED or ROUTED",
        )
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_limit_invalid",
            "claimable scan limit must be an integer",
        )
    if not 1 <= limit <= MAX_CLAIMABLE_SCAN_LIMIT:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_limit_invalid",
            f"claimable scan limit must be between 1 and {MAX_CLAIMABLE_SCAN_LIMIT}",
        )
    return normalized_state, limit, _validate_cursor(after)


def validate_recoverable_scan(
    *,
    observed_at: object,
    limit: object,
    after: Mapping[str, Any] | None = None,
) -> tuple[str, int, dict[str, str] | None]:
    normalized_observed_at = _required_string(observed_at, "observed_at")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_limit_invalid",
            "recoverable scan limit must be an integer",
        )
    if not 1 <= limit <= MAX_CLAIMABLE_SCAN_LIMIT:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_limit_invalid",
            f"recoverable scan limit must be between 1 and {MAX_CLAIMABLE_SCAN_LIMIT}",
        )
    return normalized_observed_at, limit, _validate_cursor(after)


def project_claimable_work_item(record: Mapping[str, Any]) -> dict[str, Any]:
    state = _required_string(record.get("state"), "state")
    action = action_for_work_item_state(state)
    version = record.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_version_invalid",
            "claimable WorkItem version must be a positive integer",
        )
    work_item = record.get("work_item")
    trace_id = record.get("trace_id")
    if trace_id is None and isinstance(work_item, Mapping):
        trace = work_item.get("trace")
        if isinstance(trace, Mapping):
            trace_id = trace.get("correlation_id")
    projection = {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "tenant_id": _required_string(record.get("tenant_id"), "tenant_id"),
        "work_item_id": _required_string(
            record.get("work_item_id"), "work_item_id"
        ),
        "state": state,
        "action": action,
        "expected_version": version,
        "trace_id": _required_string(trace_id, "trace_id"),
        "created_at": _required_string(record.get("created_at"), "created_at"),
        "updated_at": _required_string(record.get("updated_at"), "updated_at"),
    }
    return projection


def claimable_cursor(candidate: Mapping[str, Any]) -> dict[str, str]:
    projected = validate_claimable_work_item(candidate)
    return {
        "created_at": projected["created_at"],
        "tenant_id": projected["tenant_id"],
        "work_item_id": projected["work_item_id"],
    }


def validate_claimable_work_item(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_candidate_invalid",
            "claimable WorkItem candidate must be an object",
        )
    expected_fields = {
        "schema_version",
        "tenant_id",
        "work_item_id",
        "state",
        "action",
        "expected_version",
        "trace_id",
        "created_at",
        "updated_at",
    }
    if set(candidate) != expected_fields:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_candidate_invalid",
            "claimable WorkItem candidate fields are invalid",
        )
    if candidate.get("schema_version") != ASSIGNMENT_DISPATCH_SCHEMA_VERSION:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_schema_invalid",
            "claimable WorkItem candidate schema is invalid",
        )
    projected = project_claimable_work_item(
        {
            "tenant_id": candidate.get("tenant_id"),
            "work_item_id": candidate.get("work_item_id"),
            "state": candidate.get("state"),
            "version": candidate.get("expected_version"),
            "trace_id": candidate.get("trace_id"),
            "created_at": candidate.get("created_at"),
            "updated_at": candidate.get("updated_at"),
        }
    )
    if dict(candidate) != projected:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_candidate_invalid",
            "claimable WorkItem candidate semantics are invalid",
        )
    return projected


def build_assignment_dispatch_job(
    candidate: Mapping[str, Any],
    *,
    created_at: str | None = None,
    max_attempts: int = DEFAULT_DISPATCH_MAX_ATTEMPTS,
) -> dict[str, Any]:
    projected = validate_claimable_work_item(candidate)
    identity = _dispatch_identity(projected)
    idempotency_key = semantic_sha256_hash_ref(identity)
    job = build_common_job(
        job_id=_job_id(idempotency_key),
        job_type=WC_ASSIGNMENT_DISPATCH_JOB_TYPE,
        trace_id=projected["trace_id"],
        request_id=projected["work_item_id"],
        subject_ref=build_subject_ref(
            WC_WORK_ITEM_SUBJECT_TYPE, projected["work_item_id"]
        ),
        idempotency_key=idempotency_key,
        created_at=created_at,
        max_attempts=max_attempts,
        retryable=True,
        links={
            "tenant_id": projected["tenant_id"],
            "dispatch_action": projected["action"],
        },
    )
    job["payload"] = {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "tenant_id": projected["tenant_id"],
        "work_item_id": projected["work_item_id"],
        "expected_version": projected["expected_version"],
        "action": projected["action"],
    }
    return validate_assignment_dispatch_job(job)


def validate_assignment_dispatch_job(job: Mapping[str, Any]) -> dict[str, Any]:
    normalized = validate_common_job(dict(job))
    if normalized["job_type"] != WC_ASSIGNMENT_DISPATCH_JOB_TYPE:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_job_type_invalid",
            "assignment dispatcher job type is invalid",
        )
    payload = normalized.get("payload")
    expected_payload_fields = {
        "schema_version",
        "tenant_id",
        "work_item_id",
        "expected_version",
        "action",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_payload_fields:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_job_payload_invalid",
            "assignment dispatcher job payload is invalid",
        )
    if payload.get("schema_version") != ASSIGNMENT_DISPATCH_SCHEMA_VERSION:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_schema_invalid",
            "assignment dispatcher job schema is invalid",
        )
    tenant_id = _required_string(payload.get("tenant_id"), "tenant_id")
    work_item_id = _required_string(payload.get("work_item_id"), "work_item_id")
    action = _required_string(payload.get("action"), "action")
    if action not in ASSIGNMENT_DISPATCH_ACTIONS:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_action_invalid",
            "assignment dispatcher action must be ROUTE, CLAIM, or RECLAIM",
        )
    expected_version = payload.get("expected_version")
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version < 1
    ):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_version_invalid",
            "assignment dispatcher expected_version must be positive",
        )
    subject_ref = normalized["subject_ref"]
    if subject_ref != build_subject_ref(WC_WORK_ITEM_SUBJECT_TYPE, work_item_id):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_subject_invalid",
            "assignment dispatcher subject does not match its payload",
        )
    if normalized["request_id"] != work_item_id:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_request_invalid",
            "assignment dispatcher request does not match its payload",
        )
    if normalized["links"] != {
        "tenant_id": tenant_id,
        "dispatch_action": action,
    }:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_links_invalid",
            "assignment dispatcher links do not match its payload",
        )
    identity = {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "domain": "WC_ASSIGNMENT_DISPATCH",
        "tenant_id": tenant_id,
        "work_item_id": work_item_id,
        "expected_version": expected_version,
        "action": action,
    }
    idempotency_key = semantic_sha256_hash_ref(identity)
    if normalized["idempotency_key"] != idempotency_key:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_identity_invalid",
            "assignment dispatcher idempotency identity is invalid",
        )
    if normalized["job_id"] != _job_id(idempotency_key):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_identity_invalid",
            "assignment dispatcher job identity is invalid",
        )
    normalized["payload"] = dict(payload)
    return normalized


def action_for_work_item_state(state: object) -> str:
    normalized = _required_string(state, "state")
    action = ACTION_BY_STATE.get(normalized)
    if action is None:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_state_terminal",
            f"WorkItem state is not claimable: {normalized}",
        )
    return action


def classify_assignment_dispatch_failure(
    *, error_code: object, retryable: object = False
) -> str:
    normalized = _required_string(error_code, "error_code")
    if not isinstance(retryable, bool):
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_retryable_invalid",
            "retryable must be a boolean",
        )
    if retryable or normalized == NO_ELIGIBLE_AGENT_ERROR:
        return RETRY
    if normalized in STALE_DISPATCH_ERRORS:
        return RELOAD
    return TERMINAL


def enqueue_claimable_assignment_jobs(
    *,
    repository: AssignmentDispatchRepository,
    queue: JobQueue,
    state: str,
    limit: int,
    after: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_state, normalized_limit, cursor = validate_claimable_scan(
        state=state,
        limit=limit,
        after=after,
    )
    candidates = repository.list_claimable_work_items(
        state=normalized_state,
        limit=normalized_limit,
        after=cursor,
    )
    jobs = []
    for candidate in candidates:
        job = build_assignment_dispatch_job(candidate, created_at=created_at)
        try:
            jobs.append(queue.enqueue(job))
        except JobQueueError as exc:
            if exc.error_code != "job.duplicate_id":
                raise
            existing = queue.get_job(str(job["job_id"]))
            if existing is None or not _same_dispatch_job(existing, job):
                raise AssignmentDispatchContractError(
                    "wc.assignment_dispatch_job_conflict",
                    "existing assignment dispatch job has different semantics",
                ) from exc
            jobs.append(existing)
    return {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "state": normalized_state,
        "action": ACTION_BY_STATE[normalized_state],
        "scanned_count": len(candidates),
        "enqueued_count": len(jobs),
        "job_ids": [str(job["job_id"]) for job in jobs],
        "next_cursor": claimable_cursor(candidates[-1]) if candidates else cursor,
    }


def enqueue_recoverable_assignment_jobs(
    *,
    repository: AssignmentDispatchRepository,
    queue: JobQueue,
    observed_at: str,
    limit: int,
    after: Mapping[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_at, normalized_limit, cursor = validate_recoverable_scan(
        observed_at=observed_at,
        limit=limit,
        after=after,
    )
    candidates = repository.list_recoverable_work_items(
        observed_at=normalized_at,
        limit=normalized_limit,
        after=cursor,
    )
    jobs = []
    for candidate in candidates:
        job = build_assignment_dispatch_job(candidate, created_at=created_at)
        try:
            jobs.append(queue.enqueue(job))
        except JobQueueError as exc:
            if exc.error_code != "job.duplicate_id":
                raise
            existing = queue.get_job(str(job["job_id"]))
            if existing is None or not _same_dispatch_job(existing, job):
                raise AssignmentDispatchContractError(
                    "wc.assignment_dispatch_job_conflict",
                    "existing assignment recovery job has different semantics",
                ) from exc
            jobs.append(existing)
    return {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "state": RECOVERABLE_WORK_ITEM_STATE,
        "action": RECLAIM,
        "observed_at": normalized_at,
        "scanned_count": len(candidates),
        "enqueued_count": len(jobs),
        "job_ids": [str(job["job_id"]) for job in jobs],
        "next_cursor": claimable_cursor(candidates[-1]) if candidates else cursor,
    }


def _same_dispatch_job(
    existing: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    immutable_fields = (
        "job_schema_version",
        "job_id",
        "job_type",
        "trace_id",
        "request_id",
        "subject_ref",
        "idempotency_key",
        "max_attempts",
        "retryable",
        "links",
        "payload",
    )
    return all(existing.get(field) == expected.get(field) for field in immutable_fields)


def run_assignment_dispatch_job(
    job: Mapping[str, Any],
    *,
    repository: AssignmentDispatchRepository,
    service: AssignmentDispatchService,
) -> dict[str, Any]:
    try:
        normalized = validate_assignment_dispatch_job(job)
        payload = normalized["payload"]
        tenant_id = str(payload["tenant_id"])
        work_item_id = str(payload["work_item_id"])
        expected_version = int(payload["expected_version"])
        action = str(payload["action"])
        record = repository.get_work_item(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
        )
        if record is None:
            raise AssignmentDispatchExecutionError(
                "wc.work_item_not_found",
                "WorkItem was not found while executing assignment dispatch.",
                TERMINAL,
            )
        if action == ROUTE:
            return _run_route(
                service=service,
                record=record,
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                expected_version=expected_version,
            )
        return _run_claim(
            repository=repository,
            service=service,
            record=record,
            tenant_id=tenant_id,
            work_item_id=work_item_id,
            expected_version=expected_version,
            reclaim=action == RECLAIM,
        )
    except AssignmentDispatchExecutionError:
        raise
    except AssignmentDispatchContractError as exc:
        raise AssignmentDispatchExecutionError(
            exc.error_code,
            exc.detail,
            TERMINAL,
        ) from exc
    except Exception as exc:
        error_code = str(
            getattr(exc, "error_code", "wc.assignment_dispatch_execution_failed")
        )
        detail = str(getattr(exc, "detail", exc.__class__.__name__))
        retryable = bool(getattr(exc, "retryable", False))
        raise AssignmentDispatchExecutionError(
            error_code,
            detail,
            classify_assignment_dispatch_failure(
                error_code=error_code,
                retryable=retryable,
            ),
        ) from exc


def run_assignment_dispatch_worker_once(
    *,
    queue: JobQueue,
    heartbeat_emitter: WorkerHeartbeatEmitter,
    repository: AssignmentDispatchRepository,
    service: AssignmentDispatchService,
    worker_id: str,
    service_log_emitter: ServiceLogEmitter | None = None,
    clock: Callable[[], str] | None = None,
) -> WorkerJobExecution:
    def handler(job: dict[str, Any]) -> dict[str, Any]:
        try:
            return run_assignment_dispatch_job(
                job,
                repository=repository,
                service=service,
            )
        except AssignmentDispatchExecutionError as exc:
            resolved = exc
            if exc.disposition == RELOAD:
                try:
                    return run_assignment_dispatch_job(
                        job,
                        repository=repository,
                        service=service,
                    )
                except AssignmentDispatchExecutionError as reload_exc:
                    resolved = reload_exc
                    if reload_exc.disposition == RELOAD:
                        resolved = AssignmentDispatchExecutionError(
                            "wc.assignment_dispatch_stale_unresolved",
                            "Assignment dispatch remained stale after an authority reload.",
                            TERMINAL,
                        )
            if resolved.disposition == TERMINAL:
                queue.dead_letter_job(
                    str(job["job_id"]),
                    error=build_job_error(
                        error_code=resolved.error_code,
                        detail=resolved.detail,
                        retryable=False,
                    ),
                    failed_at=clock() if clock is not None else None,
                )
            raise resolved

    return run_worker_once(
        config=WorkerRunnerConfig(
            service_id="nex-wc",
            worker_id=worker_id,
            worker_type=WC_ASSIGNMENT_DISPATCH_WORKER_TYPE,
            job_type=WC_ASSIGNMENT_DISPATCH_JOB_TYPE,
        ),
        queue=queue,
        heartbeat_emitter=heartbeat_emitter,
        handler=handler,
        service_log_emitter=service_log_emitter,
        clock=clock,
    )


def _run_route(
    *,
    service: AssignmentDispatchService,
    record: Mapping[str, Any],
    tenant_id: str,
    work_item_id: str,
    expected_version: int,
) -> dict[str, Any]:
    state = str(record.get("state"))
    version = int(record.get("version", 0))
    route = record.get("latest_routing_decision")
    if (
        state == "ROUTED"
        and version == expected_version + 1
        and isinstance(route, Mapping)
        and route.get("decision") == "ROUTED"
    ):
        return _route_result(route, replayed=True)
    if state != "CREATED" or version != expected_version:
        raise AssignmentDispatchExecutionError(
            "wc.work_item_route_conflict",
            "WorkItem is not at the expected CREATED version.",
            RELOAD,
        )
    result = service.route(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=expected_version,
    )
    if result.get("decision") != "ROUTED":
        raise AssignmentDispatchExecutionError(
            NO_ELIGIBLE_AGENT_ERROR,
            "No eligible Agent is currently available for the WorkItem.",
            RETRY,
        )
    return _route_result(result, replayed=False)


def _run_claim(
    *,
    repository: AssignmentDispatchRepository,
    service: AssignmentDispatchService,
    record: Mapping[str, Any],
    tenant_id: str,
    work_item_id: str,
    expected_version: int,
    reclaim: bool = False,
) -> dict[str, Any]:
    state = str(record.get("state"))
    version = int(record.get("version", 0))
    if state == "ASSIGNED" and version == expected_version + 1:
        authority = repository.get_current_assignment_authority(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
        )
        if authority is not None:
            return _claim_result(authority, replayed=True)
    expected_state = "ASSIGNED" if reclaim else "ROUTED"
    if state != expected_state or version != expected_version:
        raise AssignmentDispatchExecutionError(
            "wc.work_item_claim_conflict",
            f"WorkItem is not at the expected {expected_state} version.",
            RELOAD,
        )
    result = service.claim(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        expected_version=expected_version,
    )
    return _claim_result(result, replayed=False, reclaimed=reclaim)


def _route_result(route: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
    return {
        "outcome": "ROUTE_REPLAYED" if replayed else "ROUTED",
        "routing_decision_id": str(route["routing_decision_id"]),
        "target_agent_id": str(route["target_ref"]),
        "policy_version": str(route["policy_version"]),
    }


def _claim_result(
    result: Mapping[str, Any], *, replayed: bool, reclaimed: bool = False
) -> dict[str, Any]:
    assignment = result["assignment"]
    claim = result["claim"]
    return {
        "outcome": (
            "CLAIM_REPLAYED"
            if replayed
            else "CLAIM_RECLAIMED"
            if reclaimed
            else "CLAIMED"
        ),
        "assignment_id": str(assignment["assignment_id"]),
        "claim_id": str(claim["claim_id"]),
        "claim_generation": int(claim["claim_generation"]),
        "agent_id": str(assignment["agent_id"]),
        "outbox_id": str(result["outbox_id"]),
        "event_id": str(result["event_id"]),
    }


def _dispatch_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": ASSIGNMENT_DISPATCH_SCHEMA_VERSION,
        "domain": "WC_ASSIGNMENT_DISPATCH",
        "tenant_id": candidate["tenant_id"],
        "work_item_id": candidate["work_item_id"],
        "expected_version": candidate["expected_version"],
        "action": candidate["action"],
    }


def _job_id(idempotency_key: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/jobs/wc/assignment-dispatch/"
            f"{idempotency_key}",
        )
    )


def _validate_cursor(after: Mapping[str, Any] | None) -> dict[str, str] | None:
    if after is None:
        return None
    if not isinstance(after, Mapping) or set(after) != {
        "created_at",
        "tenant_id",
        "work_item_id",
    }:
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_cursor_invalid",
            "claimable scan cursor fields are invalid",
        )
    return {
        "created_at": _required_string(after.get("created_at"), "created_at"),
        "tenant_id": _required_string(after.get("tenant_id"), "tenant_id"),
        "work_item_id": _required_string(
            after.get("work_item_id"), "work_item_id"
        ),
    }


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssignmentDispatchContractError(
            "wc.assignment_dispatch_value_invalid",
            f"{field} must be a non-empty string",
        )
    return value.strip()
