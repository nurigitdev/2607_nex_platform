from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.runtime_jobs import RuntimeJobError, SqlAlchemyRuntimeJobQueue

RESUME_TARGET_KINDS = frozenset({"EXECUTABLE_STEP", "PRODUCT_COORDINATOR"})
PRODUCT_RESUME_DISPATCH_CONTRACT_VERSION = "ae.product_coordinator_resume_dispatch.v1"


@dataclass
class RuntimeResumeError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ResumeRoute:
    tenant_id: str
    runtime_job_id: str
    execution_id: str
    wait_id: str
    event_id: str
    resume_target_kind: str
    executable_step_id: str | None
    payload: dict[str, Any]
    product_context: dict[str, Any] | None = None


class RuntimeEventMatcher:
    """Atomically satisfies a validated wait and schedules exactly one resume."""

    def __init__(self, runtime_jobs: SqlAlchemyRuntimeJobQueue) -> None:
        self._runtime_jobs = runtime_jobs

    def match_in_session(
        self,
        session: Session,
        *,
        tenant_id: str,
        wait_id: str,
        event_id: str,
        execution_id: str,
        executable_step_id: str | None,
        resume_target_kind: str,
        runtime_job_id: str,
        dedup_key: str,
        run_after: str,
        correlation_id: str,
        now: str,
        payload: Mapping[str, Any],
        causation_id: str,
    ) -> dict[str, Any]:
        target = _target(resume_target_kind)
        _target_shape(target, executable_step_id)
        params = {
            "tenant_id": _required(tenant_id, "tenant_id"),
            "wait_id": _required(wait_id, "wait_id"),
            "event_id": _required(event_id, "event_id"),
        }
        context = _load_match_context(session, params, lock=True)
        if context is None:
            raise _error(
                "ae.runtime_resume_context_not_found",
                "Runtime resume requires an existing wait and event.",
            )
        _require_context(
            context,
            execution_id=execution_id,
            executable_step_id=executable_step_id,
            resume_target_kind=target,
        )
        if context["wait_state"] == "RESUME_QUEUED":
            if (
                context["event_state"] != "MATCHED"
                or _optional_text(context["matched_event_id"]) != params["event_id"]
                or _optional_text(context["resume_runtime_job_id"]) != runtime_job_id
            ):
                raise _conflict("Matched wait and event resume lineage differs.")
            existing = self._runtime_jobs.get_in_session(
                session,
                tenant_id=params["tenant_id"],
                runtime_job_id=runtime_job_id,
            )
            if existing is None:
                raise _conflict("Matched wait resume job is missing.")
            job = self._runtime_jobs.enqueue_resume_in_session(
                session,
                tenant_id=params["tenant_id"],
                runtime_job_id=runtime_job_id,
                execution_id=execution_id,
                executable_step_id=executable_step_id,
                wait_id=params["wait_id"],
                dedup_key=dedup_key,
                run_after=existing["run_after"],
                correlation_id=correlation_id,
                now=now,
                payload=payload,
                causation_id=causation_id,
                resume_target_kind=target,
            )
            return _match_projection(context, job)
        if context["wait_state"] != "PENDING" or context["event_state"] != "RECEIVED":
            raise _conflict("Wait or event is not available for resume matching.")
        job = self._runtime_jobs.enqueue_resume_in_session(
            session,
            tenant_id=params["tenant_id"],
            runtime_job_id=runtime_job_id,
            execution_id=execution_id,
            executable_step_id=executable_step_id,
            wait_id=params["wait_id"],
            dedup_key=dedup_key,
            run_after=run_after,
            correlation_id=correlation_id,
            now=now,
            payload=payload,
            causation_id=causation_id,
            resume_target_kind=target,
        )
        wait_update = session.execute(
            text(_SATISFY_WAIT_SQL),
            {
                **params,
                "runtime_job_id": job["runtime_job_id"],
                "now": now,
            },
        )
        if int(wait_update.rowcount or 0) != 1:
            raise _conflict("WaitRegistration changed before resume scheduling.")
        event_update = session.execute(text(_MATCH_EVENT_SQL), {**params, "now": now})
        if int(event_update.rowcount or 0) != 1:
            raise _conflict("External event changed before resume scheduling.")
        return {
            "wait_state": "RESUME_QUEUED",
            "event_state": "MATCHED",
            "resume_runtime_job_id": job["runtime_job_id"],
            "runtime_job": job,
        }


class SqlAlchemyProductPreparationResumeService:
    """Matches a persisted Product event without activating a coordinator."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        runtime_jobs: SqlAlchemyRuntimeJobQueue,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._matcher = RuntimeEventMatcher(runtime_jobs)
        self._clock = clock or (lambda: datetime.now(UTC))

    def reconcile(self, *, tenant_id: str, event_id: str) -> dict[str, Any]:
        tenant = _required(tenant_id, "tenant_id")
        event = _required(event_id, "event_id")
        now = _timestamp(self._clock())
        try:
            with self._sessions() as session:
                context = _load_product_context(
                    session, tenant_id=tenant, event_id=event, lock=True
                )
                if context is None:
                    raise _error(
                        "ae.product_resume_context_not_found",
                        "Product Preparation resume context was not found.",
                    )
                _require_product_context(context)
                runtime_job_id = deterministic_product_resume_job_id(
                    tenant_id=tenant,
                    wait_id=str(context["wait_id"]),
                    event_id=event,
                )
                payload = _product_resume_payload(context)
                result = self._matcher.match_in_session(
                    session,
                    tenant_id=tenant,
                    wait_id=str(context["wait_id"]),
                    event_id=event,
                    execution_id=str(context["agent_execution_id"]),
                    executable_step_id=None,
                    resume_target_kind="PRODUCT_COORDINATOR",
                    runtime_job_id=runtime_job_id,
                    dedup_key=f"product-coordinator-resume:{context['wait_id']}:{event}",
                    run_after=now,
                    correlation_id=str(context["correlation_id"]),
                    now=now,
                    payload=payload,
                    causation_id=event,
                )
                session.commit()
                return {
                    "tenant_id": tenant,
                    "event_id": event,
                    "wait_id": str(context["wait_id"]),
                    "resume_target_kind": "PRODUCT_COORDINATOR",
                    "checkpoint_id": str(context["checkpoint_id"]),
                    "checkpoint_hash": str(context["checkpoint_hash"]),
                    "coordinator_id": str(context["coordinator_id"]),
                    "coordinator_version": str(context["coordinator_version"]),
                    **{
                        key: result[key]
                        for key in (
                            "event_state",
                            "wait_state",
                            "resume_runtime_job_id",
                        )
                    },
                }
        except RuntimeResumeError:
            raise
        except RuntimeJobError as exc:
            raise RuntimeResumeError(exc.error_code, exc.detail, exc.retryable) from exc
        except SQLAlchemyError as exc:
            raise _error(
                "ae.runtime_resume_unavailable",
                "Runtime resume persistence is unavailable.",
                True,
            ) from exc


class SqlAlchemyResumeRouteSource:
    """Resolves a queued resume job from persisted wait authority."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def resolve(self, *, tenant_id: str, runtime_job_id: str) -> ResumeRoute:
        params = {
            "tenant_id": _required(tenant_id, "tenant_id"),
            "runtime_job_id": _required(runtime_job_id, "runtime_job_id"),
        }
        try:
            with self._sessions() as session:
                row = (
                    session.execute(text(_RESUME_ROUTE_SQL), params).mappings().first()
                )
                if row is None:
                    raise _error(
                        "ae.runtime_resume_route_not_found",
                        "Runtime resume route was not found.",
                    )
                route = _route_from_row(row)
                _require_route(route)
                return route
        except RuntimeResumeError:
            raise
        except SQLAlchemyError as exc:
            raise _error(
                "ae.runtime_resume_unavailable",
                "Runtime resume route persistence is unavailable.",
                True,
            ) from exc


class ResumeTargetHandlerRegistry:
    """Dispatches a resolved route; registration alone does not activate a worker."""

    def __init__(self, handlers: Mapping[str, Callable[[ResumeRoute], Any]]) -> None:
        normalized: dict[str, Callable[[ResumeRoute], Any]] = {}
        for key, handler in handlers.items():
            target = _target(key)
            if target in normalized or not callable(handler):
                raise _error(
                    "ae.runtime_resume_handler_invalid",
                    "Resume target handler registration is invalid.",
                )
            normalized[target] = handler
        self._handlers = normalized

    def dispatch(self, route: ResumeRoute) -> Any:
        if not isinstance(route, ResumeRoute):
            raise _error("ae.runtime_resume_route_invalid", "Resume route is invalid.")
        handler = self._handlers.get(route.resume_target_kind)
        if handler is None:
            raise _error(
                "ae.runtime_resume_handler_unavailable",
                "No handler is registered for the resume target.",
                True,
            )
        return handler(route)


def deterministic_product_resume_job_id(
    *, tenant_id: str, wait_id: str, event_id: str
) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            "https://nex-platform.local/ae/runtime-jobs/product-coordinator-resume/"
            f"{tenant_id}/{wait_id}/{event_id}",
        )
    )


def _load_match_context(
    session: Session, params: Mapping[str, str], *, lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF wait, event" if lock and _postgres(session) else ""
    row = (
        session.execute(text(_MATCH_CONTEXT_SQL + suffix), dict(params))
        .mappings()
        .first()
    )
    return None if row is None else dict(row)


def _require_context(
    context: Mapping[str, Any],
    *,
    execution_id: str,
    executable_step_id: str | None,
    resume_target_kind: str,
) -> None:
    if str(context["agent_execution_id"]) != _required(execution_id, "execution_id"):
        raise _conflict("Resume execution lineage differs from the wait authority.")
    observed_step = _optional_text(context["executable_step_id"])
    if observed_step != _optional_text(executable_step_id):
        raise _conflict("Resume step lineage differs from the wait authority.")
    _target_shape(resume_target_kind, observed_step)


def _match_projection(
    context: Mapping[str, Any], job: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "wait_state": str(context["wait_state"]),
        "event_state": str(context["event_state"]),
        "resume_runtime_job_id": str(job["runtime_job_id"]),
        "runtime_job": dict(job),
    }


def _load_product_context(
    session: Session, *, tenant_id: str, event_id: str, lock: bool
) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF wait, event" if lock and _postgres(session) else ""
    row = (
        session.execute(
            text(_PRODUCT_CONTEXT_SQL + suffix),
            {"tenant_id": tenant_id, "event_id": event_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    value = dict(row)
    value["event_payload"] = _json_object(value["event_payload"])
    return value


def _require_product_context(value: Mapping[str, Any]) -> None:
    if (
        value["event_family"] != "PRODUCT_PREPARATION"
        or value["wait_type"] != "PRODUCT_PREPARATION"
        or value["resume_target_kind"] != "PRODUCT_COORDINATOR"
        or value["executable_step_id"] is not None
    ):
        raise _conflict("Product Preparation resume target differs.")
    equal_groups = (
        ("event_type", "expected_event_type"),
        ("event_external_ref", "wait_external_ref"),
        ("event_external_ref", "authority_ref"),
        ("event_wait_id", "wait_id"),
        ("event_checkpoint_id", "checkpoint_id"),
        ("event_checkpoint_hash", "checkpoint_hash"),
        ("event_coordinator_id", "coordinator_id"),
        ("event_coordinator_version", "coordinator_version"),
        ("event_coordinator_hash", "coordinator_registration_hash"),
        ("event_authority_kind", "authority_kind"),
        ("event_execution_id", "agent_execution_id"),
        ("event_work_intent_id", "work_intent_id"),
        ("checkpoint_execution_id", "agent_execution_id"),
        ("checkpoint_work_intent_id", "work_intent_id"),
        ("checkpoint_coordinator_id", "coordinator_id"),
        ("checkpoint_coordinator_version", "coordinator_version"),
        ("checkpoint_coordinator_hash", "coordinator_registration_hash"),
    )
    if any(str(value[left]) != str(value[right]) for left, right in equal_groups):
        raise _conflict("Product Preparation persisted lineage differs.")
    if value["event_payload"].get("notification_ref") != value["notification_ref"]:
        raise _conflict("Product Preparation notification lineage differs.")


def _product_resume_payload(context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "resume_target_kind": "PRODUCT_COORDINATOR",
        "dispatch_contract_version": PRODUCT_RESUME_DISPATCH_CONTRACT_VERSION,
        "wait_id": str(context["wait_id"]),
        "event_id": str(context["event_id"]),
        "checkpoint_id": str(context["checkpoint_id"]),
        "checkpoint_hash": str(context["checkpoint_hash"]),
        "coordinator_id": str(context["coordinator_id"]),
        "coordinator_version": str(context["coordinator_version"]),
        "coordinator_registration_hash": str(context["coordinator_registration_hash"]),
    }


def _route_from_row(row: Mapping[str, Any]) -> ResumeRoute:
    payload = _json_object(row["payload_json"])
    product_context = None
    if (
        row["resume_target_kind"] == "PRODUCT_COORDINATOR"
        and row["checkpoint_id"] is not None
    ):
        product_context = {
            key: (str(row[key]) if row[key] is not None else None)
            for key in (
                "checkpoint_id",
                "checkpoint_hash",
                "coordinator_id",
                "coordinator_version",
                "coordinator_registration_hash",
                "work_intent_id",
            )
        }
    return ResumeRoute(
        tenant_id=str(row["tenant_id"]),
        runtime_job_id=str(row["runtime_job_id"]),
        execution_id=str(row["execution_id"]),
        wait_id=str(row["wait_id"]),
        event_id=str(row["matched_event_id"]),
        resume_target_kind=str(row["resume_target_kind"]),
        executable_step_id=_optional_text(row["executable_step_id"]),
        payload=payload,
        product_context=product_context,
    )


def _require_route(route: ResumeRoute) -> None:
    target = _target(route.resume_target_kind)
    _target_shape(target, route.executable_step_id)
    if (
        route.payload.get("wait_id") != route.wait_id
        or route.payload.get("event_id") != route.event_id
    ):
        raise _conflict("Resume job payload references differ from wait authority.")
    if target == "PRODUCT_COORDINATOR":
        if route.product_context is None:
            raise _conflict("Product Coordinator resume binding is incomplete.")
        expected = {
            "dispatch_contract_version": PRODUCT_RESUME_DISPATCH_CONTRACT_VERSION,
            "resume_target_kind": target,
            **{
                key: route.product_context[key]
                for key in (
                    "checkpoint_id",
                    "checkpoint_hash",
                    "coordinator_id",
                    "coordinator_version",
                    "coordinator_registration_hash",
                )
            },
        }
        if any(route.payload.get(key) != value for key, value in expected.items()):
            raise _conflict(
                "Product Coordinator resume payload differs from authority."
            )


def _target(value: object) -> str:
    normalized = _required(value, "resume_target_kind").upper()
    if normalized not in RESUME_TARGET_KINDS:
        raise _error(
            "ae.runtime_resume_target_invalid", "Resume target kind is invalid."
        )
    return normalized


def _target_shape(target: str, executable_step_id: object) -> None:
    if target == "EXECUTABLE_STEP" and _optional_text(executable_step_id) is None:
        raise _error(
            "ae.runtime_resume_target_invalid",
            "Executable-step resume requires executable_step_id.",
        )
    if target == "PRODUCT_COORDINATOR" and executable_step_id is not None:
        raise _error(
            "ae.runtime_resume_target_invalid",
            "Product Coordinator resume cannot reference executable_step_id.",
        )


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise _conflict("Resume payload is not valid JSON.") from exc
    if not isinstance(parsed, Mapping):
        raise _conflict("Resume payload must be an object.")
    return dict(parsed)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _error(
            "ae.runtime_resume_invalid", "Runtime resume clock must be timezone-aware."
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "ae.runtime_resume_invalid", f"{field} must be a non-empty string."
        )
    return value.strip()


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _conflict(detail: str) -> RuntimeResumeError:
    return _error("ae.runtime_resume_conflict", detail)


def _error(error_code: str, detail: str, retryable: bool = False) -> RuntimeResumeError:
    return RuntimeResumeError(error_code, detail, retryable)


_MATCH_CONTEXT_SQL = """
SELECT wait.agent_execution_id, wait.executable_step_id,
       wait.state AS wait_state, wait.matched_event_id,
       wait.resume_runtime_job_id, event.state AS event_state
FROM ae_wait_registration AS wait
JOIN ae_external_event_inbox AS event
  ON event.tenant_id = wait.tenant_id AND event.event_id = :event_id
WHERE wait.tenant_id = :tenant_id AND wait.wait_id = :wait_id
"""

_SATISFY_WAIT_SQL = """
UPDATE ae_wait_registration
SET state = 'RESUME_QUEUED', matched_event_id = :event_id,
    resume_runtime_job_id = :runtime_job_id,
    satisfied_at = COALESCE(satisfied_at, :now), updated_at = :now,
    version = version + 1
WHERE tenant_id = :tenant_id AND wait_id = :wait_id AND state = 'PENDING'
"""

_MATCH_EVENT_SQL = """
UPDATE ae_external_event_inbox
SET state = 'MATCHED', processed_at = :now
WHERE tenant_id = :tenant_id AND event_id = :event_id AND state = 'RECEIVED'
"""

_PRODUCT_CONTEXT_SQL = """
SELECT event.event_id, event.event_family, event.event_type,
       event.external_ref AS event_external_ref, event.event_payload,
       wait.wait_id, wait.agent_execution_id, wait.executable_step_id,
       wait.wait_type, wait.external_ref AS wait_external_ref,
       wait.resume_target_kind,
       wait_binding.checkpoint_id, wait_binding.checkpoint_hash,
       wait_binding.coordinator_id, wait_binding.coordinator_version,
       wait_binding.coordinator_registration_hash,
       wait_binding.expected_event_type, wait_binding.authority_kind,
       wait_binding.authority_ref, wait_binding.work_intent_id,
       event_binding.wait_id AS event_wait_id,
       event_binding.checkpoint_id AS event_checkpoint_id,
       event_binding.checkpoint_hash AS event_checkpoint_hash,
       event_binding.coordinator_id AS event_coordinator_id,
       event_binding.coordinator_version AS event_coordinator_version,
       event_binding.coordinator_registration_hash AS event_coordinator_hash,
       event_binding.authority_kind AS event_authority_kind,
       event_binding.notification_ref,
       event_binding.agent_execution_id AS event_execution_id,
       event_binding.work_intent_id AS event_work_intent_id,
       checkpoint.agent_execution_id AS checkpoint_execution_id,
       checkpoint.work_intent_id AS checkpoint_work_intent_id,
       checkpoint.coordinator_id AS checkpoint_coordinator_id,
       checkpoint.coordinator_version AS checkpoint_coordinator_version,
       checkpoint.coordinator_registration_hash AS checkpoint_coordinator_hash,
       checkpoint.correlation_id
FROM ae_external_event_inbox AS event
JOIN ae_product_prep_event_binding AS event_binding
  ON event_binding.tenant_id = event.tenant_id
 AND event_binding.event_id = event.event_id
JOIN ae_wait_registration AS wait
  ON wait.tenant_id = event_binding.tenant_id
 AND wait.wait_id = event_binding.wait_id
JOIN ae_product_prep_wait_binding AS wait_binding
  ON wait_binding.tenant_id = wait.tenant_id
 AND wait_binding.wait_id = wait.wait_id
JOIN ae_product_prep_checkpoint AS checkpoint
  ON checkpoint.tenant_id = wait_binding.tenant_id
 AND checkpoint.checkpoint_id = wait_binding.checkpoint_id
WHERE event.tenant_id = :tenant_id AND event.event_id = :event_id
"""

_RESUME_ROUTE_SQL = """
SELECT job.tenant_id, job.runtime_job_id, job.job_type, job.execution_id,
       job.executable_step_id, job.wait_id, job.payload_json,
       wait.agent_execution_id, wait.resume_target_kind, wait.state AS wait_state,
       wait.matched_event_id, wait.resume_runtime_job_id,
       binding.checkpoint_id, binding.checkpoint_hash, binding.coordinator_id,
       binding.coordinator_version, binding.coordinator_registration_hash,
       binding.work_intent_id
FROM ae_runtime_job AS job
JOIN ae_wait_registration AS wait
  ON wait.tenant_id = job.tenant_id
 AND CAST(wait.wait_id AS TEXT) = job.wait_id
LEFT JOIN ae_product_prep_wait_binding AS binding
  ON binding.tenant_id = wait.tenant_id AND binding.wait_id = wait.wait_id
WHERE job.tenant_id = :tenant_id AND job.runtime_job_id = :runtime_job_id
  AND job.job_type = 'RESUME_EXECUTION'
  AND wait.state = 'RESUME_QUEUED'
  AND CAST(wait.resume_runtime_job_id AS TEXT) = CAST(job.runtime_job_id AS TEXT)
  AND CAST(wait.agent_execution_id AS TEXT) = job.execution_id
"""
