from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

from nex_runtime import (
    BUSY,
    ERROR,
    IDLE,
    STARTING,
    STOPPED,
    STOPPING,
    WorkerHeartbeatEmitter,
    WorkerHeartbeatError,
    WorkerHeartbeatStore,
    worker_heartbeat_is_stale,
)
from nex_runtime.nsl_package_admission import (
    NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION,
    NslPackageAdmissionError,
    inspect_installed_nsl_package,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.nsl_backend_profiles import (
    DEFAULT_NSL_V01_BACKEND_PROFILE,
    NSL_V01_BACKEND_PROFILES,
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_ae_api.runtime_jobs import RuntimeJobClaim

AE_AGENT_RUNTIME_WORKER_PROFILE_SCHEMA_VERSION = "1.0"
AE_AGENT_RUNTIME_WORKER_READINESS_SCHEMA_VERSION = (
    "ae_agent_runtime_worker_readiness.v1"
)
AE_AGENT_RUNTIME_WORKER_RUN_SCHEMA_VERSION = "ae_agent_runtime_worker_run.v1"
AE_AGENT_RUNTIME_WORKER_CHECK_SCHEMA_VERSION = "ae_agent_runtime_worker_check.v1"

AE_AGENT_RUNTIME_WORKER_SERVICE_ID = "nex-ae-api"
AE_AGENT_RUNTIME_WORKER_TYPE = "ae.agent_runtime.worker"
LOCAL_SKILL_EXECUTOR = "LOCAL_SKILL"
SNAPSHOT_REQUIRED = "SNAPSHOT_REQUIRED"

WORKER_MODES = frozenset({"disabled", "enabled"})
EVIDENCE_POLICIES = frozenset({SNAPSHOT_REQUIRED})
MAX_CONCURRENT_CLAIMS = 64
MAX_LEASE_SECONDS = 3_600
MAX_POLL_INTERVAL_SECONDS = 60.0
MAX_BOUNDED_CYCLES = 10_000
MAX_HEARTBEAT_STALE_AFTER_SECONDS = 86_400

WORKER_MODE_ENV = "NEX_AE_AGENT_WORKER_MODE"
WORKER_ID_ENV = "NEX_AE_AGENT_WORKER_ID"
WORKER_EXECUTOR_KINDS_ENV = "NEX_AE_AGENT_WORKER_EXECUTOR_KINDS"
WORKER_BACKEND_PROFILES_ENV = "NEX_AE_AGENT_WORKER_BACKEND_PROFILES"
WORKER_MAX_CONCURRENT_CLAIMS_ENV = "NEX_AE_AGENT_WORKER_MAX_CONCURRENT_CLAIMS"
WORKER_LEASE_SECONDS_ENV = "NEX_AE_AGENT_WORKER_LEASE_SECONDS"
WORKER_POLL_INTERVAL_SECONDS_ENV = "NEX_AE_AGENT_WORKER_POLL_INTERVAL_SECONDS"
WORKER_HEARTBEAT_STALE_AFTER_SECONDS_ENV = (
    "NEX_AE_AGENT_WORKER_HEARTBEAT_STALE_AFTER_SECONDS"
)
WORKER_NSL_WHEEL_LOCK_ENV = "NEX_AE_AGENT_WORKER_NSL_WHEEL_LOCK"

DEFAULT_NSL_WHEEL_LOCK = (
    Path(__file__).resolve().parents[3] / "deployment" / "locks" / "nsl-v0.1-wheel.json"
)
DEFAULT_PLATFORM_PYTHON_LOCK = (
    Path(__file__).resolve().parents[3]
    / "deployment"
    / "locks"
    / "python-production.lock"
)

WorkerClock = Callable[[], str]
WorkerSleeper = Callable[[float], None]


@dataclass(frozen=True)
class AgentRuntimeWorkerError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgentRuntimeWorkerProfile:
    worker_id: str
    supported_executor_kinds: tuple[str, ...]
    supported_backend_profiles: tuple[str, ...]
    max_concurrent_claims: int
    evidence_policy: str
    process_isolation_required: bool
    declared_at: str
    schema_version: str = AE_AGENT_RUNTIME_WORKER_PROFILE_SCHEMA_VERSION

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "worker_id": self.worker_id,
            "supported_executor_kinds": list(self.supported_executor_kinds),
            "supported_backend_profiles": list(self.supported_backend_profiles),
            "max_concurrent_claims": self.max_concurrent_claims,
            "evidence_policy": self.evidence_policy,
            "process_isolation_required": self.process_isolation_required,
            "declared_at": self.declared_at,
        }

    @property
    def profile_hash(self) -> str:
        return semantic_sha256_hash_ref(self.to_record())


@dataclass(frozen=True)
class AgentRuntimeWorkerConfig:
    mode: str
    profile: AgentRuntimeWorkerProfile
    lease_seconds: int = 60
    poll_interval_seconds: float = 1.0
    heartbeat_stale_after_seconds: int = 60

    def __post_init__(self) -> None:
        if self.mode not in WORKER_MODES:
            raise _invalid("mode must be disabled or enabled.")
        _bounded_int(
            self.lease_seconds,
            "lease_seconds",
            minimum=1,
            maximum=MAX_LEASE_SECONDS,
        )
        _bounded_float(
            self.poll_interval_seconds,
            "poll_interval_seconds",
            minimum=0.0,
            maximum=MAX_POLL_INTERVAL_SECONDS,
        )
        _bounded_int(
            self.heartbeat_stale_after_seconds,
            "heartbeat_stale_after_seconds",
            minimum=1,
            maximum=MAX_HEARTBEAT_STALE_AFTER_SECONDS,
        )


@dataclass(frozen=True)
class AgentRuntimeAssignment:
    tenant_id: str
    executor_kind: str
    backend_profile: str
    claim: RuntimeJobClaim

    @property
    def runtime_job_id(self) -> str:
        return _required_text(
            self.claim.job.get("runtime_job_id"), "claim.runtime_job_id"
        )


class AgentRuntimeAssignmentSource(Protocol):
    def claim_next(
        self,
        *,
        worker_id: str,
        supported_executor_kinds: Sequence[str],
        supported_backend_profiles: Sequence[str],
        lease_seconds: int,
        observed_at: str,
    ) -> AgentRuntimeAssignment | None: ...


class AgentRuntimeAssignmentHandler(Protocol):
    def __call__(self, assignment: AgentRuntimeAssignment) -> Mapping[str, Any]: ...


@dataclass
class AgentRuntimeShutdownToken:
    requested: bool = False
    reason_code: str | None = None

    def request(self, reason_code: str) -> None:
        self.requested = True
        self.reason_code = _required_text(reason_code, "reason_code")


class AgentRuntimeWorkerLifecycle:
    def __init__(
        self,
        *,
        profile: AgentRuntimeWorkerProfile,
        emitter: WorkerHeartbeatEmitter,
        store: WorkerHeartbeatStore,
    ) -> None:
        if emitter.store is not store:
            raise _invalid("lifecycle emitter and readiness store must match.")
        if emitter.service_id != AE_AGENT_RUNTIME_WORKER_SERVICE_ID:
            raise _invalid("worker heartbeat service_id must be nex-ae-api.")
        if emitter.worker_id != profile.worker_id:
            raise _invalid("worker heartbeat identity must match the profile.")
        if emitter.worker_type != AE_AGENT_RUNTIME_WORKER_TYPE:
            raise _invalid("worker heartbeat type must be ae.agent_runtime.worker.")
        self.profile = profile
        self.emitter = emitter
        self.store = store
        self._shutdown_requested = False
        self._active_assignments: dict[str, AgentRuntimeAssignment] = {}
        self._emissions: list[dict[str, Any]] = []

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @property
    def can_claim(self) -> bool:
        return (
            not self._shutdown_requested
            and len(self._active_assignments) < self.profile.max_concurrent_claims
        )

    @property
    def active_claim_count(self) -> int:
        return len(self._active_assignments)

    @property
    def emissions(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._emissions))

    def starting(self, *, observed_at: str | None = None) -> dict[str, Any]:
        return self._emit(STARTING, observed_at=observed_at)

    def idle(self, *, observed_at: str | None = None) -> dict[str, Any]:
        if self._shutdown_requested:
            return self.stopping(observed_at=observed_at)
        return self._emit(IDLE, observed_at=observed_at)

    def begin_assignment(
        self,
        assignment: AgentRuntimeAssignment,
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        normalized = validate_agent_runtime_assignment(assignment, self.profile)
        if self._shutdown_requested:
            raise AgentRuntimeWorkerError(
                "ae.agent_runtime_worker.draining",
                "A draining Agent Runtime worker cannot accept another assignment.",
            )
        if len(self._active_assignments) >= self.profile.max_concurrent_claims:
            raise AgentRuntimeWorkerError(
                "ae.agent_runtime_worker.capacity_exhausted",
                "Agent Runtime worker active claim capacity is exhausted.",
                True,
            )
        runtime_job_id = normalized.runtime_job_id
        if runtime_job_id in self._active_assignments:
            raise _invalid("runtime assignment is already active.")
        self._active_assignments[runtime_job_id] = normalized
        return self._emit(
            BUSY,
            active_job_id=runtime_job_id,
            metadata={"active_claim_count": self.active_claim_count},
            observed_at=observed_at,
        )

    def finish_assignment(
        self,
        runtime_job_id: str,
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        job_id = _required_text(runtime_job_id, "runtime_job_id")
        if self._active_assignments.pop(job_id, None) is None:
            raise _invalid("runtime assignment is not active.")
        if self._shutdown_requested:
            return self.stopping(observed_at=observed_at)
        return self._emit(
            IDLE,
            metadata={"active_claim_count": self.active_claim_count},
            observed_at=observed_at,
        )

    def fail_assignment(
        self,
        runtime_job_id: str,
        *,
        error_code: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        job_id = _required_text(runtime_job_id, "runtime_job_id")
        if self._active_assignments.pop(job_id, None) is None:
            raise _invalid("runtime assignment is not active.")
        return self._emit(
            ERROR,
            active_job_id=job_id,
            metadata={
                "active_claim_count": self.active_claim_count,
                "error_code": _required_text(error_code, "error_code"),
                "lease_settlement": "LEFT_TO_RUNTIME_JOB_AUTHORITY",
            },
            observed_at=observed_at,
        )

    def request_shutdown(
        self,
        *,
        reason_code: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        self._shutdown_requested = True
        return self._emit(
            STOPPING,
            active_job_id=self._single_active_job_id(),
            metadata={
                "reason_code": _required_text(reason_code, "reason_code"),
                "active_claim_count": self.active_claim_count,
            },
            observed_at=observed_at,
        )

    def stopping(self, *, observed_at: str | None = None) -> dict[str, Any]:
        self._shutdown_requested = True
        return self._emit(
            STOPPING,
            active_job_id=self._single_active_job_id(),
            metadata={"active_claim_count": self.active_claim_count},
            observed_at=observed_at,
        )

    def stopped(self, *, observed_at: str | None = None) -> dict[str, Any]:
        if self._active_assignments:
            raise AgentRuntimeWorkerError(
                "ae.agent_runtime_worker.active_claims_remain",
                "Agent Runtime worker cannot stop while claims remain active.",
                True,
            )
        self._shutdown_requested = True
        return self._emit(
            STOPPED,
            metadata={"active_claim_count": 0},
            observed_at=observed_at,
        )

    def readiness(
        self,
        *,
        stale_after_seconds: int = 60,
        checked_at: str | None = None,
    ) -> dict[str, Any]:
        heartbeat = self.store.get_heartbeat(
            AE_AGENT_RUNTIME_WORKER_SERVICE_ID, self.profile.worker_id
        )
        return project_agent_runtime_worker_readiness(
            heartbeat,
            expected_profile_hash=self.profile.profile_hash,
            stale_after_seconds=stale_after_seconds,
            checked_at=checked_at,
        )

    def _single_active_job_id(self) -> str | None:
        if len(self._active_assignments) != 1:
            return None
        return next(iter(self._active_assignments))

    def _emit(
        self,
        status: str,
        *,
        active_job_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        try:
            heartbeat = self.emitter.emit(
                status=status,
                active_job_id=active_job_id,
                metadata={
                    **agent_runtime_worker_profile_metadata(self.profile),
                    **(dict(metadata) if metadata is not None else {}),
                },
                observed_at=observed_at,
            )
        except WorkerHeartbeatError as exc:
            raise AgentRuntimeWorkerError(
                "ae.agent_runtime_worker.heartbeat_unavailable",
                "Agent Runtime worker heartbeat persistence is unavailable.",
                True,
            ) from exc
        self._emissions.append(deepcopy(heartbeat))
        return heartbeat


def build_agent_runtime_worker_profile(
    *,
    worker_id: str,
    declared_at: str,
    supported_executor_kinds: Sequence[str] = (LOCAL_SKILL_EXECUTOR,),
    supported_backend_profiles: Sequence[str] = (DEFAULT_NSL_V01_BACKEND_PROFILE,),
    max_concurrent_claims: int = 1,
    evidence_policy: str = SNAPSHOT_REQUIRED,
    process_isolation_required: bool | None = None,
) -> AgentRuntimeWorkerProfile:
    normalized_backends = _normalized_values(
        supported_backend_profiles, "supported_backend_profiles"
    )
    resolved_isolation = (
        NSL_V01_PROCESS_ISOLATED_BACKEND in normalized_backends
        if process_isolation_required is None
        else _required_bool(process_isolation_required, "process_isolation_required")
    )
    profile = AgentRuntimeWorkerProfile(
        worker_id=_required_text(worker_id, "worker_id"),
        supported_executor_kinds=_normalized_values(
            supported_executor_kinds, "supported_executor_kinds"
        ),
        supported_backend_profiles=normalized_backends,
        max_concurrent_claims=_bounded_int(
            max_concurrent_claims,
            "max_concurrent_claims",
            minimum=1,
            maximum=MAX_CONCURRENT_CLAIMS,
        ),
        evidence_policy=_required_text(evidence_policy, "evidence_policy"),
        process_isolation_required=resolved_isolation,
        declared_at=_timestamp(declared_at, "declared_at"),
    )
    validate_agent_runtime_worker_profile(profile.to_record())
    return profile


def validate_agent_runtime_worker_profile(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("worker profile must be an object.")
    required = {
        "schema_version",
        "worker_id",
        "supported_executor_kinds",
        "supported_backend_profiles",
        "max_concurrent_claims",
        "evidence_policy",
        "process_isolation_required",
        "declared_at",
    }
    if set(value) != required:
        raise _invalid("worker profile keys are invalid.")
    if value["schema_version"] != AE_AGENT_RUNTIME_WORKER_PROFILE_SCHEMA_VERSION:
        raise _invalid("worker profile schema version is invalid.")
    executors = _normalized_values(
        value["supported_executor_kinds"], "supported_executor_kinds"
    )
    backends = _normalized_values(
        value["supported_backend_profiles"], "supported_backend_profiles"
    )
    if not set(backends).issubset(NSL_V01_BACKEND_PROFILES):
        raise _invalid("worker backend profile is unsupported.")
    evidence_policy = _required_text(value["evidence_policy"], "evidence_policy")
    if evidence_policy not in EVIDENCE_POLICIES:
        raise _invalid("worker evidence policy is unsupported.")
    isolation = _required_bool(
        value["process_isolation_required"], "process_isolation_required"
    )
    if NSL_V01_PROCESS_ISOLATED_BACKEND in backends and not isolation:
        raise _invalid("NSL v0.1 backend requires process isolation.")
    return {
        "schema_version": AE_AGENT_RUNTIME_WORKER_PROFILE_SCHEMA_VERSION,
        "worker_id": _required_text(value["worker_id"], "worker_id"),
        "supported_executor_kinds": list(executors),
        "supported_backend_profiles": list(backends),
        "max_concurrent_claims": _bounded_int(
            value["max_concurrent_claims"],
            "max_concurrent_claims",
            minimum=1,
            maximum=MAX_CONCURRENT_CLAIMS,
        ),
        "evidence_policy": evidence_policy,
        "process_isolation_required": isolation,
        "declared_at": _timestamp(value["declared_at"], "declared_at"),
    }


def validate_agent_runtime_worker_startup(
    config: AgentRuntimeWorkerConfig,
    *,
    available_executor_kinds: Sequence[str],
    available_backend_profiles: Sequence[str],
    in_process_package_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    profile = validate_agent_runtime_worker_profile(config.profile.to_record())
    available_executors = set(
        _normalized_values(
            available_executor_kinds, "available_executor_kinds", allow_empty=True
        )
    )
    available_backends = set(
        _normalized_values(
            available_backend_profiles, "available_backend_profiles", allow_empty=True
        )
    )
    missing_executors = sorted(
        set(profile["supported_executor_kinds"]) - available_executors
    )
    missing_backends = sorted(
        set(profile["supported_backend_profiles"]) - available_backends
    )
    if config.mode == "enabled" and missing_executors:
        raise AgentRuntimeWorkerError(
            "ae.agent_runtime_worker.executor_unavailable",
            "Configured Agent Runtime executor implementation is unavailable.",
        )
    package_status = "NOT_CONFIGURED"
    if NSL_V01_IN_PROCESS_BACKEND in profile["supported_backend_profiles"]:
        package_status = _in_process_package_status(in_process_package_readiness)
        if config.mode == "enabled" and package_status != "PASS":
            raise AgentRuntimeWorkerError(
                "ae.agent_runtime_worker.nsl_package_unready",
                "Admitted in-process NSL package readiness is unavailable.",
            )
    if config.mode == "enabled" and missing_backends:
        raise AgentRuntimeWorkerError(
            "ae.agent_runtime_worker.backend_unavailable",
            "Configured Agent Runtime backend implementation is unavailable.",
        )
    return {
        "startup_schema_version": "ae_agent_runtime_worker_startup.v1",
        "mode": config.mode,
        "worker_id": profile["worker_id"],
        "profile_hash": config.profile.profile_hash,
        "configured_executor_kinds": profile["supported_executor_kinds"],
        "configured_backend_profiles": profile["supported_backend_profiles"],
        "missing_executor_kinds": missing_executors,
        "missing_backend_profiles": missing_backends,
        "in_process_package_status": package_status,
        "startup_ready": config.mode == "enabled"
        and not missing_executors
        and not missing_backends,
    }


def validate_agent_runtime_assignment(
    assignment: AgentRuntimeAssignment,
    profile: AgentRuntimeWorkerProfile,
) -> AgentRuntimeAssignment:
    if not isinstance(assignment, AgentRuntimeAssignment):
        raise _invalid("assignment source returned an invalid assignment.")
    _required_text(assignment.tenant_id, "tenant_id")
    executor_kind = _required_text(assignment.executor_kind, "executor_kind")
    backend_profile = _required_text(assignment.backend_profile, "backend_profile")
    if executor_kind not in profile.supported_executor_kinds:
        raise AgentRuntimeWorkerError(
            "ae.agent_runtime_worker.executor_unsupported",
            "Worker cannot execute the assigned executor kind.",
        )
    if backend_profile not in profile.supported_backend_profiles:
        raise AgentRuntimeWorkerError(
            "ae.agent_runtime_worker.backend_unsupported",
            "Worker cannot execute the assigned backend profile.",
        )
    job = assignment.claim.job
    if job.get("tenant_id") != assignment.tenant_id:
        raise _invalid("assignment tenant does not match the RuntimeJob claim.")
    if job.get("state") != "RUNNING":
        raise _invalid("assignment RuntimeJob claim must be RUNNING.")
    _required_text(job.get("lease_token"), "claim.lease_token")
    _required_text(job.get("lease_owner"), "claim.lease_owner")
    return assignment


def project_agent_runtime_worker_readiness(
    heartbeat: Mapping[str, Any] | None,
    *,
    expected_profile_hash: str,
    stale_after_seconds: int = 60,
    checked_at: str | None = None,
) -> dict[str, Any]:
    profile_hash = _required_hash(expected_profile_hash, "expected_profile_hash")
    if heartbeat is None:
        return _readiness_record(
            readiness="NOT_READY",
            reason_code="heartbeat_missing",
            profile_hash=profile_hash,
        )
    normalized = dict(heartbeat)
    metadata = normalized.get("metadata")
    observed_profile_hash = (
        metadata.get("capability_profile_hash")
        if isinstance(metadata, Mapping)
        else None
    )
    if observed_profile_hash != profile_hash:
        return _readiness_record(
            readiness="NOT_READY",
            reason_code="capability_profile_mismatch",
            profile_hash=profile_hash,
            heartbeat=normalized,
        )
    if worker_heartbeat_is_stale(
        normalized,
        stale_after_seconds=stale_after_seconds,
        checked_at=checked_at,
    ):
        return _readiness_record(
            readiness="NOT_READY",
            reason_code="heartbeat_stale",
            profile_hash=profile_hash,
            heartbeat=normalized,
        )
    status = normalized.get("status")
    if status in {IDLE, BUSY}:
        readiness = "READY"
        reason = "worker_idle" if status == IDLE else "worker_busy"
    else:
        readiness = "NOT_READY"
        reason = f"worker_{str(status).lower()}"
    return _readiness_record(
        readiness=readiness,
        reason_code=reason,
        profile_hash=profile_hash,
        heartbeat=normalized,
    )


def run_bounded_agent_runtime_worker(
    *,
    config: AgentRuntimeWorkerConfig,
    assignment_source: AgentRuntimeAssignmentSource,
    handler: AgentRuntimeAssignmentHandler,
    lifecycle: AgentRuntimeWorkerLifecycle,
    available_executor_kinds: Sequence[str],
    available_backend_profiles: Sequence[str],
    in_process_package_readiness: Mapping[str, Any] | None = None,
    max_cycles: int,
    shutdown_token: AgentRuntimeShutdownToken | None = None,
    stop_on_failure: bool = True,
    clock: WorkerClock | None = None,
    sleeper: WorkerSleeper | None = None,
) -> dict[str, Any]:
    if lifecycle.profile != config.profile:
        raise _invalid("runtime lifecycle profile does not match worker config.")
    cycles = _bounded_int(
        max_cycles,
        "max_cycles",
        minimum=1,
        maximum=MAX_BOUNDED_CYCLES,
    )
    if not isinstance(stop_on_failure, bool):
        raise _invalid("stop_on_failure must be a boolean.")
    validate_agent_runtime_worker_startup(
        config,
        available_executor_kinds=available_executor_kinds,
        available_backend_profiles=available_backend_profiles,
        in_process_package_readiness=in_process_package_readiness,
    )
    if config.mode != "enabled":
        raise AgentRuntimeWorkerError(
            "ae.agent_runtime_worker.disabled",
            "Agent Runtime worker execution is disabled.",
        )
    observed_clock = clock or _utc_now
    observed_sleeper = sleeper or time.sleep
    token = shutdown_token or AgentRuntimeShutdownToken()
    started_at = observed_clock()
    lifecycle.starting(observed_at=started_at)
    lifecycle.idle(observed_at=observed_clock())
    executions: list[dict[str, Any]] = []
    idle_cycles = 0
    stop_reason = "MAX_CYCLES"

    for cycle_number in range(1, cycles + 1):
        if token.requested or lifecycle.shutdown_requested:
            stop_reason = token.reason_code or "SHUTDOWN_REQUESTED"
            break
        assignment = assignment_source.claim_next(
            worker_id=config.profile.worker_id,
            supported_executor_kinds=config.profile.supported_executor_kinds,
            supported_backend_profiles=config.profile.supported_backend_profiles,
            lease_seconds=config.lease_seconds,
            observed_at=observed_clock(),
        )
        if assignment is None:
            idle_cycles += 1
            lifecycle.idle(observed_at=observed_clock())
            if cycle_number < cycles and config.poll_interval_seconds > 0:
                observed_sleeper(config.poll_interval_seconds)
            continue

        normalized = validate_agent_runtime_assignment(assignment, config.profile)
        runtime_job_id = normalized.runtime_job_id
        lifecycle.begin_assignment(normalized, observed_at=observed_clock())
        try:
            result = handler(normalized)
            if not isinstance(result, Mapping):
                raise _invalid("assignment handler result must be an object.")
            executions.append(
                _execution_record(
                    cycle_number=cycle_number,
                    assignment=normalized,
                    status="SUCCEEDED",
                    handler_result=result,
                )
            )
            lifecycle.finish_assignment(runtime_job_id, observed_at=observed_clock())
        except Exception as exc:  # noqa: BLE001 - worker boundary contains handlers.
            error_code = _safe_error_code(exc)
            lifecycle.fail_assignment(
                runtime_job_id,
                error_code=error_code,
                observed_at=observed_clock(),
            )
            executions.append(
                _execution_record(
                    cycle_number=cycle_number,
                    assignment=normalized,
                    status="FAILED",
                    error_code=error_code,
                )
            )
            if stop_on_failure:
                stop_reason = "FAILURE"
                break

    lifecycle.request_shutdown(
        reason_code=stop_reason,
        observed_at=observed_clock(),
    )
    lifecycle.stopped(observed_at=observed_clock())
    completed_at = observed_clock()
    return {
        "run_schema_version": AE_AGENT_RUNTIME_WORKER_RUN_SCHEMA_VERSION,
        "worker_id": config.profile.worker_id,
        "worker_type": AE_AGENT_RUNTIME_WORKER_TYPE,
        "profile_hash": config.profile.profile_hash,
        "stop_reason": stop_reason,
        "cycle_count": min(cycles, idle_cycles + len(executions)),
        "idle_cycle_count": idle_cycles,
        "claimed_count": len(executions),
        "succeeded_count": sum(item["status"] == "SUCCEEDED" for item in executions),
        "failed_count": sum(item["status"] == "FAILED" for item in executions),
        "started_at": _timestamp(started_at, "started_at"),
        "completed_at": _timestamp(completed_at, "completed_at"),
        "executions": executions,
        "heartbeat_statuses": [item["status"] for item in lifecycle.emissions],
        "content_included": False,
    }


def load_agent_runtime_worker_config(
    environ: Mapping[str, str] | None = None,
    *,
    declared_at: str | None = None,
) -> AgentRuntimeWorkerConfig:
    env = os.environ if environ is None else environ
    mode = str(env.get(WORKER_MODE_ENV, "disabled")).strip().lower()
    worker_id = str(env.get(WORKER_ID_ENV, "ae-agent-runtime-worker-1")).strip()
    backend_profiles = _csv_values(
        env.get(WORKER_BACKEND_PROFILES_ENV),
        (DEFAULT_NSL_V01_BACKEND_PROFILE,),
    )
    profile = build_agent_runtime_worker_profile(
        worker_id=worker_id,
        declared_at=declared_at or _utc_now(),
        supported_executor_kinds=_csv_values(
            env.get(WORKER_EXECUTOR_KINDS_ENV), (LOCAL_SKILL_EXECUTOR,)
        ),
        supported_backend_profiles=backend_profiles,
        max_concurrent_claims=_env_int(
            env, WORKER_MAX_CONCURRENT_CLAIMS_ENV, default=1
        ),
        process_isolation_required=(
            NSL_V01_PROCESS_ISOLATED_BACKEND in backend_profiles
        ),
    )
    return AgentRuntimeWorkerConfig(
        mode=mode,
        profile=profile,
        lease_seconds=_env_int(env, WORKER_LEASE_SECONDS_ENV, default=60),
        poll_interval_seconds=_env_float(
            env, WORKER_POLL_INTERVAL_SECONDS_ENV, default=1.0
        ),
        heartbeat_stale_after_seconds=_env_int(
            env, WORKER_HEARTBEAT_STALE_AFTER_SECONDS_ENV, default=60
        ),
    )


def agent_runtime_worker_profile_metadata(
    profile: AgentRuntimeWorkerProfile,
) -> dict[str, Any]:
    return {
        "capability_profile_hash": profile.profile_hash,
        "supported_executor_kinds": list(profile.supported_executor_kinds),
        "supported_backend_profiles": list(profile.supported_backend_profiles),
        "max_concurrent_claims": profile.max_concurrent_claims,
        "evidence_policy": profile.evidence_policy,
        "process_isolation_required": profile.process_isolation_required,
    }


def install_agent_runtime_worker_signal_handlers(
    token: AgentRuntimeShutdownToken,
) -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def request_shutdown(signum: int, _frame: Any) -> None:
        token.request(signal.Signals(signum).name)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_shutdown)
    return previous


def restore_agent_runtime_worker_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def build_agent_runtime_worker_check(
    config: AgentRuntimeWorkerConfig,
    *,
    available_executor_kinds: Sequence[str] = (),
    available_backend_profiles: Sequence[str] = (),
    in_process_package_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        startup = validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=available_executor_kinds,
            available_backend_profiles=available_backend_profiles,
            in_process_package_readiness=in_process_package_readiness,
        )
    except AgentRuntimeWorkerError as exc:
        return {
            "check_schema_version": AE_AGENT_RUNTIME_WORKER_CHECK_SCHEMA_VERSION,
            "status": "FAIL",
            "mode": config.mode,
            "worker_id": config.profile.worker_id,
            "profile_hash": config.profile.profile_hash,
            "failure_code": exc.error_code,
            "detail": exc.detail,
        }
    return {
        "check_schema_version": AE_AGENT_RUNTIME_WORKER_CHECK_SCHEMA_VERSION,
        "status": "PASS",
        **startup,
        "execution_composed": startup["startup_ready"],
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    available_executor_kinds: Sequence[str] = (),
    available_backend_profiles: Sequence[str] = (),
    in_process_package_readiness: Mapping[str, Any] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="NeX AE Agent Runtime worker")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the P6 worker profile and composed implementations.",
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    output = stdout or sys.stdout
    try:
        config = load_agent_runtime_worker_config(environ)
    except (AgentRuntimeWorkerError, ValueError) as exc:
        record = {
            "check_schema_version": AE_AGENT_RUNTIME_WORKER_CHECK_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": getattr(
                exc, "error_code", "ae.agent_runtime_worker.config_invalid"
            ),
            "detail": str(exc),
        }
        print(
            (
                _summary_line(record)
                if args.summary
                else json.dumps(record, sort_keys=True)
            ),
            file=output,
        )
        return 2
    if not args.check:
        record = {
            "check_schema_version": AE_AGENT_RUNTIME_WORKER_CHECK_SCHEMA_VERSION,
            "status": "FAIL",
            "mode": config.mode,
            "worker_id": config.profile.worker_id,
            "profile_hash": config.profile.profile_hash,
            "failure_code": "ae.agent_runtime_worker.execution_handler_unavailable",
            "detail": "P6-S4 LOCAL_SKILL handler composition is required before process execution.",
        }
    else:
        if (
            NSL_V01_IN_PROCESS_BACKEND in config.profile.supported_backend_profiles
            and in_process_package_readiness is None
        ):
            in_process_package_readiness = load_in_process_nsl_package_readiness(
                environ
            )
        record = build_agent_runtime_worker_check(
            config,
            available_executor_kinds=available_executor_kinds,
            available_backend_profiles=available_backend_profiles,
            in_process_package_readiness=in_process_package_readiness,
        )
    print(
        _summary_line(record) if args.summary else json.dumps(record, sort_keys=True),
        file=output,
    )
    return 0 if record["status"] == "PASS" else 2


def load_in_process_nsl_package_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    lock_path: Path | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    configured_path = env.get(WORKER_NSL_WHEEL_LOCK_ENV)
    resolved_path = (
        lock_path
        if lock_path is not None
        else (
            Path(configured_path).expanduser()
            if configured_path
            else DEFAULT_NSL_WHEEL_LOCK
        )
    )
    try:
        lock = json.loads(resolved_path.read_text(encoding="utf-8"))
        if not isinstance(lock, Mapping):
            raise NslPackageAdmissionError("NSL wheel lock must be an object")
        return inspect_installed_nsl_package(
            lock,
            platform_lock_path=DEFAULT_PLATFORM_PYTHON_LOCK,
        )
    except (
        json.JSONDecodeError,
        NslPackageAdmissionError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "schema_version": NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "ae.agent_runtime_worker.nsl_package_unready",
            "detail": str(exc),
            "in_process_profile_admissible": False,
        }


def _in_process_package_status(value: Mapping[str, Any] | None) -> str:
    if not isinstance(value, Mapping):
        return "MISSING"
    if (
        value.get("schema_version") != NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION
        or value.get("status") != "PASS"
        or value.get("distribution") != "nex-skill-language"
        or value.get("in_process_profile_admissible") is not True
    ):
        return "FAIL"
    return "PASS"


def _readiness_record(
    *,
    readiness: str,
    reason_code: str,
    profile_hash: str,
    heartbeat: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "readiness_schema_version": AE_AGENT_RUNTIME_WORKER_READINESS_SCHEMA_VERSION,
        "readiness": readiness,
        "reason_code": reason_code,
        "worker_id": None if heartbeat is None else heartbeat.get("worker_id"),
        "worker_type": None if heartbeat is None else heartbeat.get("worker_type"),
        "status": None if heartbeat is None else heartbeat.get("status"),
        "active_job_id": None if heartbeat is None else heartbeat.get("active_job_id"),
        "last_seen_at": None if heartbeat is None else heartbeat.get("last_seen_at"),
        "profile_hash": profile_hash,
    }


def _execution_record(
    *,
    cycle_number: int,
    assignment: AgentRuntimeAssignment,
    status: str,
    handler_result: Mapping[str, Any] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "cycle_number": cycle_number,
        "tenant_id": assignment.tenant_id,
        "runtime_job_id": assignment.runtime_job_id,
        "executor_kind": assignment.executor_kind,
        "backend_profile": assignment.backend_profile,
        "status": status,
        "handler_result": (
            deepcopy(dict(handler_result)) if handler_result is not None else None
        ),
        "error_code": error_code,
    }


def _normalized_values(
    values: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid(f"{field_name} must be an array of strings.")
    normalized = tuple(_required_text(item, field_name) for item in values)
    if not normalized and not allow_empty:
        raise _invalid(f"{field_name} must not be empty.")
    if len(set(normalized)) != len(normalized):
        raise _invalid(f"{field_name} must not contain duplicates.")
    return tuple(sorted(normalized))


def _csv_values(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, str):
        raise _invalid("worker capability environment value must be text.")
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_int(env: Mapping[str, str], name: str, *, default: int) -> int:
    value = env.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be an integer.") from exc


def _env_float(env: Mapping[str, str], name: str, *, default: float) -> float:
    value = env.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be a number.") from exc


def _bounded_int(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _invalid(f"{field_name} must be between {minimum} and {maximum}.")
    return value


def _bounded_float(
    value: object,
    field_name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{field_name} must be numeric.")
    normalized = float(value)
    if not minimum <= normalized <= maximum:
        raise _invalid(f"{field_name} must be between {minimum} and {maximum}.")
    return normalized


def _required_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(f"{field_name} must be a boolean.")
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-empty string.")
    return value.strip()


def _required_hash(value: object, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if not normalized.startswith("sha256:") or len(normalized) != 71:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.")
    try:
        int(normalized[7:], 16)
    except ValueError as exc:
        raise _invalid(f"{field_name} must be a SHA-256 hash reference.") from exc
    return normalized


def _timestamp(value: object, field_name: str) -> str:
    text = _required_text(value, field_name)
    try:
        observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field_name} must be an RFC3339 timestamp.") from exc
    if observed.tzinfo is None:
        raise _invalid(f"{field_name} must include a timezone.")
    return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_error_code(exc: Exception) -> str:
    value = getattr(exc, "error_code", None)
    if not isinstance(value, str) or not value.strip():
        return "ae.agent_runtime_worker.assignment_failed"
    return value.strip()[:160]


def _summary_line(record: Mapping[str, Any]) -> str:
    return (
        f"p6_s0_agent_runtime_worker={str(record.get('status', 'FAIL')).lower()} "
        f"mode={record.get('mode', 'unknown')} "
        f"worker_id={record.get('worker_id', 'unknown')} "
        f"failure_code={record.get('failure_code', 'none')}"
    )


def _invalid(detail: str) -> AgentRuntimeWorkerError:
    return AgentRuntimeWorkerError("ae.agent_runtime_worker.invalid", detail)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
