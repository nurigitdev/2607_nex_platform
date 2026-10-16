from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.agent_runtime_worker import AgentRuntimeAssignment
from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_V01_BACKEND_PROFILES,
    normalize_nsl_backend_profile,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_ae_api.step_executors import PLATFORM_EXECUTOR_KINDS

AE_RUNTIME_QUEUE_NAME = "ae-runtime"
LOCAL_SKILL_EXECUTOR = "LOCAL_SKILL"
DEFAULT_EXECUTOR_BACKENDS = {
    LOCAL_SKILL_EXECUTOR: DEFAULT_NSL_V01_BACKEND_PROFILE,
}
DISPATCHER_SCHEMA_VERSION = "ae_agent_runtime_dispatcher.v1"
DISPATCH_ROUND_SCHEMA_VERSION = "ae_agent_runtime_dispatch_round.v1"
RECONCILIATION_SCHEMA_VERSION = "ae_agent_runtime_reconciliation.v1"

DISPATCHER_ID_ENV = "NEX_AE_AGENT_DISPATCHER_ID"
DISPATCHER_QUEUE_ENV = "NEX_AE_AGENT_DISPATCHER_QUEUE"
DISPATCHER_LEASE_SECONDS_ENV = "NEX_AE_AGENT_DISPATCHER_LEASE_SECONDS"
DISPATCHER_TENANT_SNAPSHOT_ENV = "NEX_AE_AGENT_DISPATCHER_TENANT_SNAPSHOT"
DISPATCHER_BATCH_SIZE_ENV = "NEX_AE_AGENT_DISPATCHER_BATCH_SIZE"
DISPATCHER_GLOBAL_ACTIVE_CAP_ENV = "NEX_AE_AGENT_DISPATCHER_GLOBAL_ACTIVE_CAP"
DISPATCHER_TENANT_ACTIVE_CAP_ENV = "NEX_AE_AGENT_DISPATCHER_TENANT_ACTIVE_CAP"
DISPATCHER_MAX_RUNNABLE_DEPTH_ENV = "NEX_AE_AGENT_DISPATCHER_MAX_RUNNABLE_DEPTH"
DISPATCHER_ADMISSION_POLICY_ENV = "NEX_AE_AGENT_DISPATCHER_ADMISSION_POLICY"
DISPATCHER_ADMISSION_DELAY_ENV = "NEX_AE_AGENT_DISPATCHER_ADMISSION_DELAY_SECONDS"
DISPATCHER_RECONCILE_BATCH_ENV = "NEX_AE_AGENT_DISPATCHER_RECONCILE_BATCH"

MAX_LEASE_SECONDS = 300
MAX_TENANT_SNAPSHOT = 1_000
MAX_DISPATCH_BATCH = 256
MAX_ACTIVE_CLAIMS = 10_000
MAX_RUNNABLE_DEPTH = 1_000_000
MAX_ADMISSION_DELAY_SECONDS = 3_600
MAX_RECONCILE_BATCH = 1_000

DispatcherClock = Callable[[], str]


@dataclass(frozen=True)
class AgentRuntimeDispatcherError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgentRuntimeDispatcherConfig:
    dispatcher_id: str = "ae-agent-runtime-dispatcher-1"
    queue_name: str = AE_RUNTIME_QUEUE_NAME
    leadership_lease_seconds: int = 15
    tenant_snapshot_limit: int = 64
    dispatch_batch_size: int = 8
    global_active_claim_cap: int = 16
    per_tenant_active_claim_cap: int = 2
    max_runnable_depth: int = 1_000
    admission_policy: str = "DELAY"
    admission_delay_seconds: int = 5
    malformed_reconcile_batch: int = 16

    def __post_init__(self) -> None:
        _required_text(self.dispatcher_id, "dispatcher_id")
        _required_text(self.queue_name, "queue_name")
        _bounded_int(
            self.leadership_lease_seconds,
            "leadership_lease_seconds",
            maximum=MAX_LEASE_SECONDS,
        )
        _bounded_int(
            self.tenant_snapshot_limit,
            "tenant_snapshot_limit",
            maximum=MAX_TENANT_SNAPSHOT,
        )
        _bounded_int(
            self.dispatch_batch_size,
            "dispatch_batch_size",
            maximum=MAX_DISPATCH_BATCH,
        )
        _bounded_int(
            self.global_active_claim_cap,
            "global_active_claim_cap",
            maximum=MAX_ACTIVE_CLAIMS,
        )
        _bounded_int(
            self.per_tenant_active_claim_cap,
            "per_tenant_active_claim_cap",
            maximum=MAX_ACTIVE_CLAIMS,
        )
        _bounded_int(
            self.max_runnable_depth,
            "max_runnable_depth",
            maximum=MAX_RUNNABLE_DEPTH,
        )
        _bounded_int(
            self.admission_delay_seconds,
            "admission_delay_seconds",
            maximum=MAX_ADMISSION_DELAY_SECONDS,
        )
        _bounded_int(
            self.malformed_reconcile_batch,
            "malformed_reconcile_batch",
            maximum=MAX_RECONCILE_BATCH,
        )
        policy = _required_text(self.admission_policy, "admission_policy").upper()
        if policy not in {"REJECT", "DELAY"}:
            raise _invalid("admission_policy must be REJECT or DELAY.")
        if self.per_tenant_active_claim_cap > self.global_active_claim_cap:
            raise _invalid(
                "per_tenant_active_claim_cap must not exceed global_active_claim_cap."
            )
        if self.dispatch_batch_size > self.global_active_claim_cap:
            raise _invalid(
                "dispatch_batch_size must not exceed global_active_claim_cap."
            )
        if self.tenant_snapshot_limit < self.dispatch_batch_size:
            raise _invalid(
                "tenant_snapshot_limit must be at least dispatch_batch_size."
            )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": DISPATCHER_SCHEMA_VERSION,
            "dispatcher_id": self.dispatcher_id,
            "queue_name": self.queue_name,
            "leadership_lease_seconds": self.leadership_lease_seconds,
            "tenant_snapshot_limit": self.tenant_snapshot_limit,
            "dispatch_batch_size": self.dispatch_batch_size,
            "global_active_claim_cap": self.global_active_claim_cap,
            "per_tenant_active_claim_cap": self.per_tenant_active_claim_cap,
            "max_runnable_depth": self.max_runnable_depth,
            "admission_policy": self.admission_policy.upper(),
            "admission_delay_seconds": self.admission_delay_seconds,
            "malformed_reconcile_batch": self.malformed_reconcile_batch,
        }


class SqlAlchemyAgentRuntimeDispatcher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        config: AgentRuntimeDispatcherConfig | None = None,
        queue: SqlAlchemyRuntimeJobQueue | None = None,
        id_factory: Callable[[], str] | None = None,
        executor_backends: Mapping[str, str] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.config = config or AgentRuntimeDispatcherConfig()
        self.queue = queue or SqlAlchemyRuntimeJobQueue(
            session_factory,
            max_runnable_depth=self.config.max_runnable_depth,
            admission_policy=self.config.admission_policy,
            admission_delay_seconds=self.config.admission_delay_seconds,
        )
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._executor_backends = _executor_backend_map(
            DEFAULT_EXECUTOR_BACKENDS
            if executor_backends is None
            else executor_backends
        )
        if not set(self._executor_backends).issubset(PLATFORM_EXECUTOR_KINDS):
            raise _invalid("executor_backends contains an unknown platform executor.")

    def acquire_leadership(self, *, observed_at: str) -> dict[str, Any] | None:
        now = _timestamp(observed_at, "observed_at")
        lease_until = _add_seconds(now, self.config.leadership_lease_seconds)
        params = {
            "queue_name": self.config.queue_name,
            "owner_id": self.config.dispatcher_id,
            "now": now,
            "lease_until": lease_until,
        }
        try:
            with self._session_factory() as session:
                inserted = session.execute(text(_LEASE_INSERT_SQL), params)
                if int(inserted.rowcount or 0) == 1:
                    lease = _load_lease(
                        session, self.config.queue_name, for_update=False
                    )
                    session.commit()
                    return lease
                current = _load_lease(session, self.config.queue_name, for_update=True)
                if current is None:
                    session.rollback()
                    return None
                active = current["released_at"] is None and _parse_timestamp(
                    current["lease_until"], "lease_until"
                ) > _parse_timestamp(now, "observed_at")
                same_owner = current["owner_id"] == self.config.dispatcher_id
                if active and not same_owner:
                    session.rollback()
                    return None
                takeover = not active
                updated = session.execute(
                    text(_LEASE_UPDATE_SQL),
                    {
                        **params,
                        "expected_owner_id": current["owner_id"],
                        "expected_fencing_token": current["fencing_token"],
                        "fencing_token": (
                            int(current["fencing_token"]) + 1
                            if takeover
                            else int(current["fencing_token"])
                        ),
                        "acquired_at": now if takeover else current["acquired_at"],
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    session.rollback()
                    return None
                lease = _load_lease(session, self.config.queue_name, for_update=False)
                session.commit()
                return lease
        except AgentRuntimeDispatcherError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable("leadership store is unavailable") from exc

    def release_leadership(
        self,
        *,
        fencing_token: int,
        observed_at: str,
    ) -> bool:
        params = {
            "queue_name": self.config.queue_name,
            "owner_id": self.config.dispatcher_id,
            "fencing_token": _bounded_int(
                fencing_token, "fencing_token", maximum=2**63 - 1
            ),
            "now": _timestamp(observed_at, "observed_at"),
        }
        try:
            with self._session_factory() as session:
                updated = session.execute(text(_LEASE_RELEASE_SQL), params)
                session.commit()
                return int(updated.rowcount or 0) == 1
        except SQLAlchemyError as exc:
            raise _unavailable("leadership release failed") from exc

    def get_leadership(self) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                return _load_lease(session, self.config.queue_name, for_update=False)
        except SQLAlchemyError as exc:
            raise _unavailable("leadership store is unavailable") from exc

    def dispatch_round(
        self,
        *,
        worker_id: str,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str],
        lease_seconds: int,
        observed_at: str,
        assignment_limit: int | None = None,
    ) -> dict[str, Any]:
        worker = _required_text(worker_id, "worker_id")
        now = _timestamp(observed_at, "observed_at")
        lease_duration = _bounded_int(lease_seconds, "lease_seconds", maximum=3_600)
        eligible = self._eligible_executors(
            supported_executor_kinds, supported_backend_profiles
        )
        backends = _normalized_values(
            supported_backend_profiles, "supported_backend_profiles"
        )
        limit = self.config.dispatch_batch_size
        if assignment_limit is not None:
            limit = min(
                limit,
                _bounded_int(
                    assignment_limit,
                    "assignment_limit",
                    maximum=MAX_DISPATCH_BATCH,
                ),
            )
        leadership = self.acquire_leadership(observed_at=now)
        if leadership is None:
            return _round_record(
                status="STANDBY",
                queue_name=self.config.queue_name,
                assignments=(),
                candidate_tenant_count=0,
                active_claim_count=0,
                capacity=self.config.global_active_claim_cap,
            )
        active = self.active_claim_counts(observed_at=now)
        available = min(
            limit,
            max(0, self.config.global_active_claim_cap - active["global"]),
        )
        if available == 0:
            return _round_record(
                status="SATURATED",
                queue_name=self.config.queue_name,
                assignments=(),
                candidate_tenant_count=0,
                active_claim_count=active["global"],
                capacity=self.config.global_active_claim_cap,
                fencing_token=leadership["fencing_token"],
            )
        tenants = self.discover_runnable_tenants(
            supported_executor_kinds=eligible,
            supported_backend_profiles=backends,
            observed_at=now,
        )
        assignments: list[AgentRuntimeAssignment] = []
        tenant_active = dict(active["by_tenant"])
        for candidate in tenants:
            if len(assignments) >= available:
                break
            tenant_id = candidate["tenant_id"]
            if (
                tenant_active.get(tenant_id, 0)
                >= self.config.per_tenant_active_claim_cap
            ):
                continue
            claim = self.queue.claim_capability_aware(
                tenant_id=tenant_id,
                worker_id=worker,
                supported_executor_kinds=eligible,
                supported_backend_profiles=backends,
                lease_seconds=lease_duration,
                now=now,
                queue_name=self.config.queue_name,
                dispatcher_id=self.config.dispatcher_id,
                fencing_token=int(leadership["fencing_token"]),
            )
            if claim is None or claim.executor_kind is None:
                continue
            try:
                backend = normalize_nsl_backend_profile(claim.backend_profile)
            except ValueError as exc:
                raise _invalid(
                    "Claimed LOCAL_SKILL job lacks a supported persisted backend profile."
                ) from exc
            assignments.append(
                AgentRuntimeAssignment(
                    tenant_id=tenant_id,
                    executor_kind=claim.executor_kind,
                    backend_profile=backend,
                    claim=claim,
                )
            )
            tenant_active[tenant_id] = tenant_active.get(tenant_id, 0) + 1
        return _round_record(
            status="DISPATCHED" if assignments else "IDLE",
            queue_name=self.config.queue_name,
            assignments=tuple(assignments),
            candidate_tenant_count=len(tenants),
            active_claim_count=active["global"] + len(assignments),
            capacity=self.config.global_active_claim_cap,
            fencing_token=leadership["fencing_token"],
        )

    def discover_runnable_tenants(
        self,
        *,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str] | None = None,
        observed_at: str,
    ) -> tuple[dict[str, Any], ...]:
        executors = _normalized_values(
            supported_executor_kinds, "supported_executor_kinds"
        )
        backends = (
            None
            if supported_backend_profiles is None
            else _normalized_values(
                supported_backend_profiles, "supported_backend_profiles"
            )
        )
        try:
            with self._session_factory() as session:
                statement = text(
                    _runnable_tenants_sql(
                        session.get_bind().dialect.name,
                        filter_backends=backends is not None,
                    )
                ).bindparams(bindparam("executor_kinds", expanding=True))
                if backends is not None:
                    statement = statement.bindparams(
                        bindparam("backend_profiles", expanding=True)
                    )
                params = {
                    "executor_kinds": list(executors),
                    "now": _timestamp(observed_at, "observed_at"),
                    "limit": self.config.tenant_snapshot_limit,
                    **(
                        {"backend_profiles": list(backends)}
                        if backends is not None
                        else {}
                    ),
                }
                rows = session.execute(statement, params).mappings().all()
                return tuple(
                    {
                        "tenant_id": str(row["tenant_id"]),
                        "oldest_runnable_at": _datetime_value(
                            row["oldest_runnable_at"]
                        ),
                    }
                    for row in rows
                )
        except SQLAlchemyError as exc:
            raise _unavailable("runnable tenant discovery failed") from exc

    def active_claim_counts(self, *, observed_at: str) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.execute(
                        text(_ACTIVE_CLAIMS_SQL),
                        {"now": _timestamp(observed_at, "observed_at")},
                    )
                    .mappings()
                    .all()
                )
                by_tenant = {
                    str(row["tenant_id"]): int(row["active_count"]) for row in rows
                }
                return {
                    "global": sum(by_tenant.values()),
                    "by_tenant": by_tenant,
                }
        except SQLAlchemyError as exc:
            raise _unavailable("active claim projection failed") from exc

    def reconcile_malformed_jobs(
        self,
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        now = _timestamp(observed_at, "observed_at")
        try:
            with self._session_factory() as session:
                lock_suffix = (
                    " FOR UPDATE OF job SKIP LOCKED"
                    if session.get_bind().dialect.name == "postgresql"
                    else ""
                )
                statement = text(_MALFORMED_SELECT_SQL + lock_suffix).bindparams(
                    bindparam("platform_executor_kinds", expanding=True)
                )
                rows = (
                    session.execute(
                        statement,
                        {
                            "platform_executor_kinds": sorted(PLATFORM_EXECUTOR_KINDS),
                            "now": now,
                            "limit": self.config.malformed_reconcile_batch,
                        },
                    )
                    .mappings()
                    .all()
                )
                reasons: dict[str, int] = {}
                for row in rows:
                    reason = str(row["reason_code"])
                    issue_id = _required_text(self._id_factory(), "issue_id")
                    if row["state"] == "RUNNING":
                        session.execute(
                            text(_EXPIRE_ATTEMPT_SQL),
                            {
                                "tenant_id": row["tenant_id"],
                                "runtime_job_id": row["runtime_job_id"],
                                "attempt_no": row["attempt_no"],
                                "lease_token": row["lease_token"],
                                "now": now,
                            },
                        )
                    updated = session.execute(
                        text(_DEAD_LETTER_JOB_SQL),
                        {
                            "tenant_id": row["tenant_id"],
                            "runtime_job_id": row["runtime_job_id"],
                            "expected_state": row["state"],
                            "expected_lease_token": row["lease_token"],
                            "now": now,
                        },
                    )
                    if int(updated.rowcount or 0) != 1:
                        continue
                    session.execute(
                        text(_ISSUE_INSERT_SQL),
                        {
                            "issue_id": issue_id,
                            "tenant_id": row["tenant_id"],
                            "runtime_job_id": row["runtime_job_id"],
                            "reason_code": reason,
                            "executor_kind": row["executor_kind"],
                            "now": now,
                        },
                    )
                    reasons[reason] = reasons.get(reason, 0) + 1
                session.commit()
                return {
                    "schema_version": RECONCILIATION_SCHEMA_VERSION,
                    "status": "COMPLETED",
                    "reconciled_count": sum(reasons.values()),
                    "reason_counts": dict(sorted(reasons.items())),
                    "content_included": False,
                }
        except SQLAlchemyError as exc:
            raise _unavailable("malformed RuntimeJob reconciliation failed") from exc

    def get_job_issue(
        self,
        *,
        tenant_id: str,
        runtime_job_id: str,
    ) -> dict[str, Any] | None:
        params = {
            "tenant_id": _required_text(tenant_id, "tenant_id"),
            "runtime_job_id": _required_text(runtime_job_id, "runtime_job_id"),
        }
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(text(_ISSUE_SELECT_SQL), params).mappings().first()
                )
                if row is None:
                    return None
                return {
                    "issue_id": str(row["issue_id"]),
                    "tenant_id": str(row["tenant_id"]),
                    "runtime_job_id": str(row["runtime_job_id"]),
                    "reason_code": str(row["reason_code"]),
                    "observed_executor_kind": (
                        None
                        if row["observed_executor_kind"] is None
                        else str(row["observed_executor_kind"])
                    ),
                    "issue_state": str(row["issue_state"]),
                    "detected_at": _datetime_value(row["detected_at"]),
                    "acknowledged_at": _datetime_or_none(row["acknowledged_at"]),
                }
        except SQLAlchemyError as exc:
            raise _unavailable("malformed RuntimeJob issue lookup failed") from exc

    def _eligible_executors(
        self,
        executor_kinds: Sequence[str],
        backend_profiles: Sequence[str],
    ) -> tuple[str, ...]:
        executors = _normalized_values(executor_kinds, "supported_executor_kinds")
        backends = set(
            _normalized_values(
                backend_profiles, "supported_backend_profiles", allow_empty=True
            )
        )
        eligible = tuple(
            executor
            for executor in executors
            if (
                executor == LOCAL_SKILL_EXECUTOR
                and bool(backends.intersection(NSL_V01_BACKEND_PROFILES))
            )
            or (
                executor != LOCAL_SKILL_EXECUTOR
                and self._executor_backends.get(executor) in backends
            )
        )
        if not eligible:
            raise AgentRuntimeDispatcherError(
                "ae.agent_runtime_dispatcher.capability_unavailable",
                "No configured executor has a supported backend profile.",
            )
        return eligible


class SqlAlchemyAgentRuntimeAssignmentSource:
    def __init__(
        self,
        dispatcher: SqlAlchemyAgentRuntimeDispatcher,
        *,
        prefetch_limit: int = 1,
    ) -> None:
        self.dispatcher = dispatcher
        self.prefetch_limit = _bounded_int(
            prefetch_limit, "prefetch_limit", maximum=MAX_DISPATCH_BATCH
        )
        self._pending: deque[AgentRuntimeAssignment] = deque()
        self._worker_id: str | None = None
        self._lock = threading.Lock()

    def claim_next(
        self,
        *,
        worker_id: str,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str],
        lease_seconds: int,
        observed_at: str,
    ) -> AgentRuntimeAssignment | None:
        worker = _required_text(worker_id, "worker_id")
        with self._lock:
            if self._worker_id is None:
                self._worker_id = worker
            elif self._worker_id != worker:
                raise _invalid("assignment source is bound to another worker_id.")
            if self._pending:
                return self._pending.popleft()
            round_record = self.dispatcher.dispatch_round(
                worker_id=worker,
                supported_executor_kinds=supported_executor_kinds,
                supported_backend_profiles=supported_backend_profiles,
                lease_seconds=lease_seconds,
                observed_at=observed_at,
                assignment_limit=self.prefetch_limit,
            )
            self._pending.extend(round_record["assignments"])
            return self._pending.popleft() if self._pending else None


def load_agent_runtime_dispatcher_config(
    environ: Mapping[str, str] | None = None,
) -> AgentRuntimeDispatcherConfig:
    env = os.environ if environ is None else environ
    return AgentRuntimeDispatcherConfig(
        dispatcher_id=str(
            env.get(DISPATCHER_ID_ENV, "ae-agent-runtime-dispatcher-1")
        ).strip(),
        queue_name=str(env.get(DISPATCHER_QUEUE_ENV, AE_RUNTIME_QUEUE_NAME)).strip(),
        leadership_lease_seconds=_env_int(
            env, DISPATCHER_LEASE_SECONDS_ENV, default=15
        ),
        tenant_snapshot_limit=_env_int(env, DISPATCHER_TENANT_SNAPSHOT_ENV, default=64),
        dispatch_batch_size=_env_int(env, DISPATCHER_BATCH_SIZE_ENV, default=8),
        global_active_claim_cap=_env_int(
            env, DISPATCHER_GLOBAL_ACTIVE_CAP_ENV, default=16
        ),
        per_tenant_active_claim_cap=_env_int(
            env, DISPATCHER_TENANT_ACTIVE_CAP_ENV, default=2
        ),
        max_runnable_depth=_env_int(
            env, DISPATCHER_MAX_RUNNABLE_DEPTH_ENV, default=1_000
        ),
        admission_policy=str(env.get(DISPATCHER_ADMISSION_POLICY_ENV, "DELAY"))
        .strip()
        .upper(),
        admission_delay_seconds=_env_int(
            env, DISPATCHER_ADMISSION_DELAY_ENV, default=5
        ),
        malformed_reconcile_batch=_env_int(
            env, DISPATCHER_RECONCILE_BATCH_ENV, default=16
        ),
    )


def agent_runtime_dispatcher_table_sql(dialect_name: str) -> tuple[str, str]:
    timestamp_type = "TIMESTAMPTZ" if dialect_name == "postgresql" else "TEXT"
    return (
        f"""
        CREATE TABLE IF NOT EXISTS ae_rt_dispatch_lease (
            queue_name TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            fencing_token INTEGER NOT NULL,
            acquired_at {timestamp_type} NOT NULL,
            renewed_at {timestamp_type} NOT NULL,
            lease_until {timestamp_type} NOT NULL,
            released_at {timestamp_type} NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ae_rt_job_issue (
            issue_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            runtime_job_id TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            observed_executor_kind TEXT NULL,
            issue_state TEXT NOT NULL,
            detected_at {timestamp_type} NOT NULL,
            acknowledged_at {timestamp_type} NULL,
            UNIQUE (tenant_id, runtime_job_id)
        )
        """,
    )


def _round_record(
    *,
    status: str,
    queue_name: str,
    assignments: tuple[AgentRuntimeAssignment, ...],
    candidate_tenant_count: int,
    active_claim_count: int,
    capacity: int,
    fencing_token: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": DISPATCH_ROUND_SCHEMA_VERSION,
        "status": status,
        "queue_name": queue_name,
        "fencing_token": fencing_token,
        "assignments": assignments,
        "metrics": {
            "candidate_tenant_count": candidate_tenant_count,
            "claimed_count": len(assignments),
            "active_claim_count": active_claim_count,
            "capacity": capacity,
            "capacity_saturated": active_claim_count >= capacity,
        },
        "metric_labels": {"queue": queue_name, "status": status},
        "high_cardinality_labels_included": False,
    }


def _load_lease(
    session: Session, queue_name: str, *, for_update: bool
) -> dict[str, Any] | None:
    suffix = (
        " FOR UPDATE"
        if for_update and session.get_bind().dialect.name == "postgresql"
        else ""
    )
    row = (
        session.execute(text(_LEASE_SELECT_SQL + suffix), {"queue_name": queue_name})
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "queue_name": str(row["queue_name"]),
        "owner_id": str(row["owner_id"]),
        "fencing_token": int(row["fencing_token"]),
        "acquired_at": _datetime_value(row["acquired_at"]),
        "renewed_at": _datetime_value(row["renewed_at"]),
        "lease_until": _datetime_value(row["lease_until"]),
        "released_at": _datetime_or_none(row["released_at"]),
    }


_LEASE_INSERT_SQL = """
    INSERT INTO ae_rt_dispatch_lease (
        queue_name, owner_id, fencing_token, acquired_at, renewed_at,
        lease_until, released_at
    ) VALUES (
        :queue_name, :owner_id, 1, :now, :now, :lease_until, NULL
    ) ON CONFLICT (queue_name) DO NOTHING
"""

_LEASE_SELECT_SQL = """
    SELECT queue_name, owner_id, fencing_token, acquired_at, renewed_at,
           lease_until, released_at
    FROM ae_rt_dispatch_lease
    WHERE queue_name = :queue_name
"""

_LEASE_UPDATE_SQL = """
    UPDATE ae_rt_dispatch_lease
    SET owner_id = :owner_id, fencing_token = :fencing_token,
        acquired_at = :acquired_at, renewed_at = :now,
        lease_until = :lease_until, released_at = NULL
    WHERE queue_name = :queue_name
      AND owner_id = :expected_owner_id
      AND fencing_token = :expected_fencing_token
"""

_LEASE_RELEASE_SQL = """
    UPDATE ae_rt_dispatch_lease
    SET released_at = :now
    WHERE queue_name = :queue_name AND owner_id = :owner_id
      AND fencing_token = :fencing_token AND released_at IS NULL
"""

_RUNNABLE_TENANTS_SQL = """
    SELECT job.tenant_id,
           min(CASE WHEN job.state = 'RUNNING'
                    THEN job.lease_until ELSE job.run_after END)
               AS oldest_runnable_at
    FROM ae_runtime_job AS job
    JOIN ae_executable_step AS step
      ON step.tenant_id = job.tenant_id
     AND step.executable_step_id = job.executable_step_id
    WHERE step.executor_kind IN :executor_kinds
      AND ((job.state = 'QUEUED' AND job.run_after <= :now)
           OR (job.state = 'RUNNING' AND job.lease_until <= :now))
    GROUP BY job.tenant_id
    ORDER BY oldest_runnable_at, job.tenant_id
    LIMIT :limit
"""


def _runnable_tenants_sql(dialect_name: str, *, filter_backends: bool) -> str:
    if not filter_backends:
        return _RUNNABLE_TENANTS_SQL
    backend_expression = (
        "step.skill_binding_json ->> 'backend_profile'"
        if dialect_name == "postgresql"
        else "json_extract(step.skill_binding_json, '$.backend_profile')"
    )
    return _RUNNABLE_TENANTS_SQL.replace(
        "WHERE step.executor_kind IN :executor_kinds",
        "WHERE step.executor_kind IN :executor_kinds "
        f"AND {backend_expression} IN :backend_profiles",
    )


_ACTIVE_CLAIMS_SQL = """
    SELECT tenant_id, count(*) AS active_count
    FROM ae_runtime_job
    WHERE state = 'RUNNING' AND lease_until > :now
    GROUP BY tenant_id
"""

_MALFORMED_SELECT_SQL = """
    SELECT job.tenant_id, job.runtime_job_id, job.state, job.attempt_no,
           job.lease_token, step.executor_kind,
           CASE
             WHEN job.executable_step_id IS NULL THEN 'STEP_ID_MISSING'
             WHEN step.executable_step_id IS NULL THEN 'STEP_NOT_FOUND'
             WHEN step.executor_kind IS NULL THEN 'EXECUTOR_KIND_MISSING'
             ELSE 'EXECUTOR_UNSUPPORTED'
           END AS reason_code
    FROM ae_runtime_job AS job
    LEFT JOIN ae_executable_step AS step
      ON step.tenant_id = job.tenant_id
     AND step.executable_step_id = job.executable_step_id
    WHERE ((job.state = 'QUEUED' AND job.run_after <= :now)
           OR (job.state = 'RUNNING' AND job.lease_until <= :now))
      AND (
        job.executable_step_id IS NULL
        OR step.executable_step_id IS NULL
        OR step.executor_kind IS NULL
        OR step.executor_kind NOT IN :platform_executor_kinds
      )
    ORDER BY CASE WHEN job.state = 'RUNNING' THEN 0 ELSE 1 END,
             job.run_after, job.created_at, job.runtime_job_id
    LIMIT :limit
"""

_EXPIRE_ATTEMPT_SQL = """
    UPDATE ae_runtime_job_attempt
    SET outcome = 'LEASE_EXPIRED', ended_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND attempt_no = :attempt_no AND lease_token = :lease_token
      AND outcome = 'RUNNING'
"""

_DEAD_LETTER_JOB_SQL = """
    UPDATE ae_runtime_job
    SET state = 'DEAD_LETTER', lease_owner = NULL, lease_token = NULL,
        lease_until = NULL, updated_at = :now
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
      AND state = :expected_state
      AND (lease_token = :expected_lease_token OR
           (lease_token IS NULL AND :expected_lease_token IS NULL))
"""

_ISSUE_SELECT_SQL = """
    SELECT issue_id, tenant_id, runtime_job_id, reason_code,
           observed_executor_kind, issue_state, detected_at, acknowledged_at
    FROM ae_rt_job_issue
    WHERE tenant_id = :tenant_id AND runtime_job_id = :runtime_job_id
"""

_ISSUE_INSERT_SQL = """
    INSERT INTO ae_rt_job_issue (
        issue_id, tenant_id, runtime_job_id, reason_code,
        observed_executor_kind, issue_state, detected_at, acknowledged_at
    ) VALUES (
        :issue_id, :tenant_id, :runtime_job_id, :reason_code,
        :executor_kind, 'OPEN', :now, NULL
    ) ON CONFLICT (tenant_id, runtime_job_id) DO NOTHING
"""


def _executor_backend_map(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping) or not values:
        raise _invalid("executor_backends must be a non-empty object.")
    return {
        _required_text(key, "executor_kind"): _required_text(value, "backend_profile")
        for key, value in values.items()
    }


def _normalized_values(
    values: Sequence[str], field_name: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid(f"{field_name} must be an array of strings.")
    normalized = tuple(sorted({_required_text(value, field_name) for value in values}))
    if not normalized and not allow_empty:
        raise _invalid(f"{field_name} must not be empty.")
    return normalized


def _env_int(env: Mapping[str, str], name: str, *, default: int) -> int:
    raw = str(env.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise _invalid(f"{name} must be an integer.") from exc
    return value


def _bounded_int(value: object, field_name: str, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise _invalid(f"{field_name} must be between 1 and {maximum}.")
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _timestamp(value: object, field_name: str) -> str:
    return _format_timestamp(_parse_timestamp(value, field_name))


def _parse_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be an RFC 3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be an RFC 3339 timestamp.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field_name} must include a timezone.")
    return parsed.astimezone(UTC)


def _add_seconds(value: str, seconds: int) -> str:
    return _format_timestamp(
        _parse_timestamp(value, "timestamp") + timedelta(seconds=seconds)
    )


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime_value(value: Any) -> str:
    return (
        value.isoformat().replace("+00:00", "Z")
        if hasattr(value, "isoformat")
        else str(value)
    )


def _datetime_or_none(value: Any) -> str | None:
    return None if value is None else _datetime_value(value)


def _invalid(detail: str) -> AgentRuntimeDispatcherError:
    return AgentRuntimeDispatcherError("ae.agent_runtime_dispatcher.invalid", detail)


def _unavailable(detail: str) -> AgentRuntimeDispatcherError:
    return AgentRuntimeDispatcherError(
        "ae.agent_runtime_dispatcher.store_unavailable",
        f"AE Agent Runtime {detail}.",
        True,
    )
