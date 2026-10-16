from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
    normalize_nsl_backend_profile,
)
from nex_ae_api.nsl_step_executions import (
    SqlAlchemyNSLStepExecutionRepository,
    validate_context_projection,
    validate_skill_execution_request,
)
from nex_ae_api.skill_artifacts import validate_verified_skill_artifact

BACKEND_PROFILE = NSL_V01_PROCESS_ISOLATED_BACKEND
BACKEND_RUN_SCHEMA_VERSION = "1.0"
V01_CHILD_REQUEST_FORMAT = "NEX-P6-NSL-V01-CHILD-REQUEST"
V01_CHILD_RESPONSE_FORMAT = "NEX-P6-NSL-V01-CHILD-RESPONSE"
NSL_JOB_FORMAT = "NEX-NSL-SKILL-EXECUTION-JOB"
NSL_JOB_SCHEMA_VERSION = "1.0"
NSL_RESULT_FORMAT = "NEX-NSL-RUNTIME-RESULT"
NSL_RESULT_SCHEMA_VERSION = "1.0"
NSL_PROGRESS_FORMAT = "NEX-NSL-EXECUTION-PROGRESS"
NSL_PROGRESS_SCHEMA_VERSION = "1.0"
MAX_BACKEND_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_BACKEND_TIMEOUT_MS = 30_000
ISOLATION_STATUSES = frozenset(
    {"COMPLETED", "TARGET_ERROR", "CRASHED", "TIMED_OUT", "PROTOCOL_ERROR"}
)
RUNTIME_STATUSES = frozenset(
    {
        "CREATED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "TOOL_ERROR",
        "VALIDATION_ERROR",
        "LIMIT_EXCEEDED",
        "CANCELLED",
    }
)
TERMINAL_RUNTIME_STATUSES = RUNTIME_STATUSES - {"CREATED", "RUNNING"}
PROGRESS_STATES = frozenset(
    {"STARTED", "SKILL_RESOLVED", "RUNNING", "COMPLETED", "FAILED"}
)
_ISOLATION_ERRORS = {
    "TARGET_ERROR": ("ISOLATED_RUNTIME_TARGET_ERROR", False),
    "CRASHED": ("ISOLATED_RUNTIME_CRASH", True),
    "TIMED_OUT": ("ISOLATED_RUNTIME_TIMEOUT", True),
    "PROTOCOL_ERROR": ("ISOLATED_RUNTIME_PROTOCOL_ERROR", False),
}


@dataclass(frozen=True)
class NSLReadBackendError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@runtime_checkable
class NSLReadBackend(Protocol):
    backend_profile: str

    def execute(
        self,
        *,
        request: Mapping[str, Any],
        context_projection: Mapping[str, Any],
        artifact: Mapping[str, Any],
        attempt_no: int,
        started_at: str,
    ) -> dict[str, Any]: ...


@runtime_checkable
class IsolatedRuntime(Protocol):
    timeout_ms: int
    max_payload_bytes: int

    def execute(self, payload: bytes) -> object: ...


@runtime_checkable
class V01WorkerSession(Protocol):
    worker: object

    def evidence_refs(self) -> Sequence[str]: ...


class V01ProcessEntrypoint:
    """Trusted child target that uses only the stable ``nsl.api`` contracts."""

    def __init__(self, session_factory: Callable[..., V01WorkerSession]) -> None:
        if not callable(session_factory):
            raise TypeError("v0.1 worker session factory must be callable")
        self._session_factory = session_factory

    def __call__(self, payload: bytes) -> bytes:
        from nsl.api import (  # type: ignore[import-not-found]
            InMemoryProgressSink,
            SkillExecutionJob,
            SkillExecutionWorker,
        )

        child_request = _decode_child_request(payload)
        progress = InMemoryProgressSink()
        session = self._session_factory(
            child_request["backend_artifact_handle"], progress
        )
        worker = getattr(session, "worker", None)
        if not isinstance(worker, SkillExecutionWorker):
            raise TypeError("v0.1 worker session returned an invalid worker")
        evidence_reader = getattr(session, "evidence_refs", None)
        if not callable(evidence_reader):
            raise TypeError("v0.1 worker session lacks an evidence bridge")
        job = SkillExecutionJob.from_data(child_request["job"])
        envelope = asyncio.run(worker.execute(job))
        response = {
            "format": V01_CHILD_RESPONSE_FORMAT,
            "schema_version": "1.0",
            "runtime_result_envelope": envelope.to_data(),
            "progress_events": [event.to_data() for event in progress.events],
            "evidence_refs": list(evidence_reader()),
        }
        return canonical_json(response).encode("utf-8")


class V01ReadBackendAdapter:
    backend_profile = BACKEND_PROFILE

    def __init__(
        self,
        isolated_runtime: IsolatedRuntime,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(isolated_runtime, IsolatedRuntime):
            raise _dependency("v0.1 backend requires an isolated Runtime boundary.")
        timeout_ms = getattr(isolated_runtime, "timeout_ms", None)
        max_payload_bytes = getattr(isolated_runtime, "max_payload_bytes", None)
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= MAX_BACKEND_TIMEOUT_MS:
            raise _dependency("v0.1 backend timeout is outside the P6 profile.")
        if (
            type(max_payload_bytes) is not int
            or not 1 <= max_payload_bytes <= MAX_BACKEND_PAYLOAD_BYTES
        ):
            raise _dependency("v0.1 backend payload limit is outside the P6 profile.")
        self._runtime = isolated_runtime
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def timeout_ms(self) -> int:
        return self._runtime.timeout_ms

    @property
    def max_payload_bytes(self) -> int:
        return self._runtime.max_payload_bytes

    def execute(
        self,
        *,
        request: Mapping[str, Any],
        context_projection: Mapping[str, Any],
        artifact: Mapping[str, Any],
        attempt_no: int,
        started_at: str,
    ) -> dict[str, Any]:
        normalized_request = validate_skill_execution_request(request)
        normalized_context = validate_context_projection(context_projection)
        normalized_artifact = validate_verified_skill_artifact(artifact)
        attempt = _bounded_int("attempt_no", attempt_no, 1, 10_000)
        started = _timestamp("started_at", started_at)
        job = build_v01_skill_execution_job(
            request=normalized_request,
            context_projection=normalized_context,
            artifact=normalized_artifact,
        )
        child_request = {
            "format": V01_CHILD_REQUEST_FORMAT,
            "schema_version": "1.0",
            "backend_artifact_handle": normalized_artifact["backend_artifact_handle"],
            "job": job,
        }
        payload = canonical_json(child_request).encode("utf-8")
        if len(payload) > self.max_payload_bytes:
            raise _invalid("v0.1 child request exceeds the configured payload limit.")
        try:
            isolated = self._runtime.execute(payload)
        except Exception:  # noqa: BLE001 - process launch is an untrusted boundary
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=_clock_timestamp(self._clock),
                isolation_status="PROTOCOL_ERROR",
                error_code="ISOLATED_RUNTIME_START_FAILED",
                exit_code=None,
                retryable=True,
            )
        completed = _clock_timestamp(self._clock)
        status = str(getattr(isolated, "status", ""))
        if status not in ISOLATION_STATUSES:
            status = "PROTOCOL_ERROR"
        if status != "COMPLETED":
            error_code, retryable = _ISOLATION_ERRORS[status]
            supplied_error = getattr(isolated, "error_code", None)
            if isinstance(supplied_error, str) and supplied_error:
                error_code = supplied_error
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=completed,
                isolation_status=status,
                error_code=error_code,
                exit_code=getattr(isolated, "exit_code", None),
                retryable=retryable,
            )
        try:
            response = _decode_child_response(
                getattr(isolated, "payload", None),
                request=normalized_request,
                artifact=normalized_artifact,
                maximum_bytes=self.max_payload_bytes,
            )
        except NSLReadBackendError:
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=completed,
                isolation_status="PROTOCOL_ERROR",
                error_code="ISOLATED_RUNTIME_PROTOCOL_ERROR",
                exit_code=0,
                retryable=False,
            )
        envelope = response["runtime_result_envelope"]
        runtime_status = envelope["runtime_result"]["status"]
        record = {
            "schema_version": BACKEND_RUN_SCHEMA_VERSION,
            "tenant_id": normalized_request["tenant_id"],
            "executable_step_id": normalized_request["executable_step_id"],
            "nsl_execution_id": normalized_request["nsl_execution_id"],
            "business_operation_id": normalized_request["business_operation_id"],
            "attempt_no": attempt,
            "backend_profile": BACKEND_PROFILE,
            "isolation_status": "COMPLETED",
            "runtime_status": runtime_status,
            "runtime_result_envelope": envelope,
            "progress_events": response["progress_events"],
            "evidence_refs": _canonical_refs(
                [
                    *response["evidence_refs"],
                    _backend_run_ref(normalized_request["nsl_execution_id"], attempt),
                ]
            ),
            "error_code": None,
            "exit_code": 0,
            "retryable": False,
            "started_at": started,
            "completed_at": completed,
        }
        record["record_hash"] = semantic_sha256_hash_ref(record)
        return validate_nsl_backend_run(record)


class V01InProcessReadBackendAdapter:
    backend_profile = NSL_V01_IN_PROCESS_BACKEND
    timeout_semantics = "NSL_COOPERATIVE_DEADLINE"

    def __init__(
        self,
        session_factory: Callable[..., V01WorkerSession],
        *,
        api: object | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise _dependency("v0.1 in-process worker session factory is unavailable.")
        self._session_factory = session_factory
        self._api = _validated_v01_public_api(api or _load_v01_public_api())
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(
        self,
        *,
        request: Mapping[str, Any],
        context_projection: Mapping[str, Any],
        artifact: Mapping[str, Any],
        attempt_no: int,
        started_at: str,
    ) -> dict[str, Any]:
        normalized_request = validate_skill_execution_request(request)
        normalized_context = validate_context_projection(context_projection)
        normalized_artifact = validate_verified_skill_artifact(artifact)
        attempt = _bounded_int("attempt_no", attempt_no, 1, 10_000)
        started = _timestamp("started_at", started_at)
        job = build_v01_skill_execution_job(
            request=normalized_request,
            context_projection=normalized_context,
            artifact=normalized_artifact,
        )
        try:
            response = _execute_v01_in_process_session(
                api=self._api,
                session_factory=self._session_factory,
                artifact_handle=normalized_artifact["backend_artifact_handle"],
                job=job,
            )
        except NSLReadBackendError:
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=_clock_timestamp(self._clock),
                isolation_status="PROTOCOL_ERROR",
                error_code="IN_PROCESS_RUNTIME_PROTOCOL_ERROR",
                exit_code=0,
                retryable=False,
                backend_profile=self.backend_profile,
            )
        except Exception:  # noqa: BLE001 - NSL target is an execution boundary
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=_clock_timestamp(self._clock),
                isolation_status="TARGET_ERROR",
                error_code="IN_PROCESS_RUNTIME_TARGET_ERROR",
                exit_code=0,
                retryable=False,
                backend_profile=self.backend_profile,
            )
        completed = _clock_timestamp(self._clock)
        try:
            response = _validate_v01_worker_response(
                response,
                request=normalized_request,
                artifact=normalized_artifact,
            )
        except NSLReadBackendError:
            return _failed_backend_run(
                request=normalized_request,
                artifact=normalized_artifact,
                attempt_no=attempt,
                started_at=started,
                completed_at=completed,
                isolation_status="PROTOCOL_ERROR",
                error_code="IN_PROCESS_RUNTIME_PROTOCOL_ERROR",
                exit_code=0,
                retryable=False,
                backend_profile=self.backend_profile,
            )
        envelope = response["runtime_result_envelope"]
        runtime_status = envelope["runtime_result"]["status"]
        record = {
            "schema_version": BACKEND_RUN_SCHEMA_VERSION,
            "tenant_id": normalized_request["tenant_id"],
            "executable_step_id": normalized_request["executable_step_id"],
            "nsl_execution_id": normalized_request["nsl_execution_id"],
            "business_operation_id": normalized_request["business_operation_id"],
            "attempt_no": attempt,
            "backend_profile": self.backend_profile,
            "isolation_status": "COMPLETED",
            "runtime_status": runtime_status,
            "runtime_result_envelope": envelope,
            "progress_events": response["progress_events"],
            "evidence_refs": _canonical_refs(
                [
                    *response["evidence_refs"],
                    _backend_run_ref(normalized_request["nsl_execution_id"], attempt),
                ]
            ),
            "error_code": None,
            "exit_code": 0,
            "retryable": False,
            "started_at": started,
            "completed_at": completed,
        }
        record["record_hash"] = semantic_sha256_hash_ref(record)
        return validate_nsl_backend_run(record)


def build_v01_in_process_backend(
    session_factory: Callable[..., V01WorkerSession],
    *,
    clock: Callable[[], datetime] | None = None,
) -> V01InProcessReadBackendAdapter:
    return V01InProcessReadBackendAdapter(session_factory, clock=clock)


def build_v01_process_isolated_backend(
    process_target: Callable[[bytes], bytes],
    *,
    timeout_ms: int = MAX_BACKEND_TIMEOUT_MS,
    max_payload_bytes: int = MAX_BACKEND_PAYLOAD_BYTES,
    clock: Callable[[], datetime] | None = None,
) -> V01ReadBackendAdapter:
    try:
        from nsl.process_isolation import (  # type: ignore[import-not-found]
            ProcessIsolatedRuntime,
        )
    except ImportError as exc:
        raise _dependency("Configured NSL v0.1 package is unavailable.") from exc
    try:
        boundary = ProcessIsolatedRuntime(
            process_target,
            timeout_ms=timeout_ms,
            max_payload_bytes=max_payload_bytes,
        )
    except (TypeError, ValueError) as exc:
        raise _dependency(
            "NSL v0.1 process isolation configuration is invalid."
        ) from exc
    return V01ReadBackendAdapter(boundary, clock=clock)


def build_v01_skill_execution_job(
    *,
    request: Mapping[str, Any],
    context_projection: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    request = validate_skill_execution_request(request)
    context = validate_context_projection(context_projection)
    artifact = validate_verified_skill_artifact(artifact)
    if (
        request["tenant_id"] != context["verified_principal"]["tenant_id"]
        or request["context_projection_hash"] != context["projection_hash"]
        or request["agent_context_ref"] != context["agent_context_ref"]
        or request["agent_context_hash"] != context["agent_context_hash"]
    ):
        raise _invalid("v0.1 request and trusted context projection do not match.")
    if (
        request["skill_id"] != artifact["skill_id"]
        or request["exact_skill_version"] != artifact["skill_version"]
        or request["expected_semantic_hash"] != artifact["skill_semantic_hash"]
        or request["runtime_contract_ref"] != artifact["runtime_contract_ref"]
    ):
        raise _invalid("v0.1 request and verified Skill artifact do not match.")
    runtime_context = _inflate_context(context["runtime_context_entries"])
    principal = dict(context["verified_principal"])
    policy = dict(context["data_policy"])
    policy.pop("policy_ref")
    return {
        "format": NSL_JOB_FORMAT,
        "schema_version": NSL_JOB_SCHEMA_VERSION,
        "execution_id": request["nsl_execution_id"],
        "skill_id": request["skill_id"],
        "skill_version": request["exact_skill_version"],
        "expected_semantic_hash": request["expected_semantic_hash"],
        "inputs": dict(request["compiled_inputs"]),
        "input_provenance": dict(request["input_provenance"]),
        "runtime_context": runtime_context,
        "principal": principal,
        "data_policy": policy,
    }


def validate_nsl_backend_run(value: Mapping[str, Any]) -> dict[str, Any]:
    record = _canonical_mapping("NSL backend run", value)
    fields = {
        "schema_version",
        "tenant_id",
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
        "attempt_no",
        "backend_profile",
        "isolation_status",
        "runtime_status",
        "runtime_result_envelope",
        "progress_events",
        "evidence_refs",
        "error_code",
        "exit_code",
        "retryable",
        "started_at",
        "completed_at",
        "record_hash",
    }
    if set(record) != fields or record.get("schema_version") != "1.0":
        raise _invalid("NSL backend run fields or schema version are invalid.")
    _text("tenant_id", record["tenant_id"], 128)
    for field in (
        "executable_step_id",
        "nsl_execution_id",
        "business_operation_id",
    ):
        _uuid(field, record[field])
    if record["nsl_execution_id"] == record["business_operation_id"]:
        raise _invalid("NSL backend run identities must remain distinct.")
    _bounded_int("attempt_no", record["attempt_no"], 1, 10_000)
    try:
        normalize_nsl_backend_profile(record["backend_profile"])
    except ValueError as exc:
        raise _invalid("NSL backend run profile is invalid.") from exc
    isolation_status = record["isolation_status"]
    if isolation_status not in ISOLATION_STATUSES:
        raise _invalid("NSL backend run isolation status is invalid.")
    started_at = _timestamp("started_at", record["started_at"])
    completed_at = _timestamp("completed_at", record["completed_at"])
    if datetime.fromisoformat(
        completed_at.replace("Z", "+00:00")
    ) < datetime.fromisoformat(started_at.replace("Z", "+00:00")):
        raise _invalid("NSL backend run completion cannot precede its start.")
    if type(record["retryable"]) is not bool:
        raise _invalid("NSL backend run retryable must be boolean.")
    exit_code = record["exit_code"]
    if exit_code is not None and type(exit_code) is not int:
        raise _invalid("NSL backend run exit code is invalid.")
    refs = _canonical_refs(record["evidence_refs"])
    if refs != record["evidence_refs"]:
        raise _invalid("NSL backend run evidence refs must be canonical.")
    if isolation_status == "COMPLETED":
        if (
            record["error_code"] is not None
            or record["retryable"] is not False
            or exit_code != 0
        ):
            raise _invalid("Completed NSL backend isolation metadata is invalid.")
        envelope = _validate_runtime_envelope(
            record["runtime_result_envelope"],
            nsl_execution_id=record["nsl_execution_id"],
        )
        runtime_status = envelope["runtime_result"]["status"]
        if record["runtime_status"] != runtime_status:
            raise _invalid("NSL backend runtime status does not match its envelope.")
        _validate_progress_events(
            record["progress_events"],
            nsl_execution_id=record["nsl_execution_id"],
            skill_id=envelope["runtime_result"]["skill_id"],
            skill_version=envelope["runtime_result"]["skill_version"],
            runtime_status=runtime_status,
        )
    else:
        if (
            record["runtime_status"] is not None
            or record["runtime_result_envelope"] is not None
            or record["progress_events"] != []
            or not isinstance(record["error_code"], str)
            or not record["error_code"]
        ):
            raise _invalid("Failed NSL backend isolation evidence is invalid.")
        if isolation_status == "CRASHED" and exit_code in {None, 0}:
            raise _invalid("Crashed NSL backend run requires a non-zero exit code.")
    supplied_hash = _hash("record_hash", record["record_hash"])
    expected_hash = semantic_sha256_hash_ref(
        {key: item for key, item in record.items() if key != "record_hash"}
    )
    if supplied_hash != expected_hash:
        raise _invalid("NSL backend run hash does not match semantic content.")
    return record


class SqlAlchemyNSLBackendRunRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, *, record: Mapping[str, Any]) -> dict[str, Any]:
        normalized = validate_nsl_backend_run(record)
        params = _backend_run_params(normalized)
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_backend_run_insert_sql(_dialect_name(session))), params
                )
                saved = _load_backend_run(
                    session,
                    normalized["tenant_id"],
                    normalized["nsl_execution_id"],
                    normalized["attempt_no"],
                )
                if saved != normalized:
                    raise NSLReadBackendError(
                        "ae.nsl_backend_run_immutable_conflict",
                        "NSL backend attempt already has different evidence.",
                    )
                session.commit()
                return saved
        except NSLReadBackendError:
            raise
        except SQLAlchemyError as exc:
            raise NSLReadBackendError(
                "ae.nsl_backend_run_store_unavailable",
                "NSL backend run evidence store is unavailable.",
                True,
            ) from exc

    def get(
        self, *, tenant_id: str, nsl_execution_id: str, attempt_no: int
    ) -> dict[str, Any] | None:
        tenant = _text("tenant_id", tenant_id, 128)
        execution_id = _uuid("nsl_execution_id", nsl_execution_id)
        attempt = _bounded_int("attempt_no", attempt_no, 1, 10_000)
        try:
            with self._session_factory() as session:
                return _load_backend_run(session, tenant, execution_id, attempt)
        except SQLAlchemyError as exc:
            raise NSLReadBackendError(
                "ae.nsl_backend_run_store_unavailable",
                "NSL backend run evidence store is unavailable.",
                True,
            ) from exc


class NSLReadExecutionService:
    def __init__(
        self,
        *,
        bindings: SqlAlchemyNSLStepExecutionRepository,
        artifacts: object,
        backend: NSLReadBackend,
        runs: SqlAlchemyNSLBackendRunRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not all(
            callable(getattr(bindings, method, None))
            for method in ("get", "mark_invocation_started")
        ):
            raise _dependency("NSL READ service requires a binding repository.")
        if not callable(getattr(artifacts, "get", None)):
            raise _dependency("NSL READ service requires an artifact repository.")
        if not isinstance(backend, NSLReadBackend):
            raise _dependency("NSL READ service requires a configured backend.")
        try:
            self.backend_profile = normalize_nsl_backend_profile(
                backend.backend_profile
            )
        except ValueError as exc:
            raise _dependency(
                "NSL READ service backend profile is unsupported."
            ) from exc
        if not all(callable(getattr(runs, method, None)) for method in ("get", "save")):
            raise _dependency("NSL READ service requires a run evidence repository.")
        self._bindings = bindings
        self._artifacts = artifacts
        self._backend = backend
        self._runs = runs
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute_bound(
        self, *, tenant_id: str, executable_step_id: str, attempt_no: int
    ) -> dict[str, Any]:
        bundle = self._bindings.get(
            tenant_id=tenant_id, executable_step_id=executable_step_id
        )
        if bundle is None:
            raise NSLReadBackendError(
                "ae.nsl_backend_binding_not_found",
                "NSL READ requires a durable step execution binding.",
            )
        binding = bundle["binding"]
        if binding["backend_profile"] != self.backend_profile:
            raise NSLReadBackendError(
                "ae.nsl_backend_profile_mismatch",
                "Persisted NSL binding does not match the configured backend profile.",
                True,
            )
        existing = self._runs.get(
            tenant_id=tenant_id,
            nsl_execution_id=binding["nsl_execution_id"],
            attempt_no=attempt_no,
        )
        if existing is not None:
            return existing
        artifact = self._artifacts.get(
            tenant_id=tenant_id, artifact_ref=binding["verified_artifact_ref"]
        )
        if artifact is None:
            raise NSLReadBackendError(
                "ae.nsl_backend_artifact_not_found",
                "NSL READ requires its verified Skill artifact.",
            )
        started_at = _clock_timestamp(self._clock)
        running = self._bindings.mark_invocation_started(
            tenant_id=tenant_id,
            executable_step_id=executable_step_id,
            now=started_at,
        )
        record = self._backend.execute(
            request=running["request"],
            context_projection=running["context_projection"],
            artifact=artifact,
            attempt_no=attempt_no,
            started_at=running["binding"]["invocation_started_at"],
        )
        return self._runs.save(record=record)


def nsl_backend_run_table_sql(dialect_name: str) -> tuple[str, ...]:
    json_type = "TEXT" if dialect_name == "sqlite" else "JSONB"
    timestamp_type = "TEXT" if dialect_name == "sqlite" else "TIMESTAMPTZ"
    return (
        """
        CREATE UNIQUE INDEX uq_ae_nsl_step_run_ref
        ON ae_nsl_step_execution (
            tenant_id, executable_step_id, nsl_execution_id
        )
        """,
        f"""
        CREATE TABLE ae_nsl_backend_run (
            tenant_id TEXT NOT NULL,
            nsl_execution_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            executable_step_id TEXT NOT NULL,
            business_operation_id TEXT NOT NULL,
            isolation_status TEXT NOT NULL,
            runtime_status TEXT,
            record_hash TEXT NOT NULL,
            record_json {json_type} NOT NULL,
            started_at {timestamp_type} NOT NULL,
            completed_at {timestamp_type} NOT NULL,
            PRIMARY KEY (tenant_id, nsl_execution_id, attempt_no),
            FOREIGN KEY (tenant_id, executable_step_id, nsl_execution_id)
                REFERENCES ae_nsl_step_execution (
                    tenant_id, executable_step_id, nsl_execution_id
                )
        )
        """,
        "CREATE INDEX idx_ae_nsl_run_step ON ae_nsl_backend_run (tenant_id, executable_step_id, attempt_no)",
        "CREATE INDEX idx_ae_nsl_run_state ON ae_nsl_backend_run (isolation_status, runtime_status, completed_at)",
    )


def _decode_child_request(payload: bytes) -> dict[str, Any]:
    value = _canonical_bytes_object(payload, "v0.1 child request")
    if set(value) != {"format", "schema_version", "backend_artifact_handle", "job"}:
        raise _invalid("v0.1 child request fields are invalid.")
    if value["format"] != V01_CHILD_REQUEST_FORMAT or value["schema_version"] != "1.0":
        raise _invalid("v0.1 child request format is invalid.")
    _text("backend_artifact_handle", value["backend_artifact_handle"], 512)
    if not isinstance(value["job"], Mapping):
        raise _invalid("v0.1 child request job is invalid.")
    return value


def _decode_child_response(
    payload: object,
    *,
    request: Mapping[str, Any],
    artifact: Mapping[str, Any],
    maximum_bytes: int,
) -> dict[str, Any]:
    if type(payload) is not bytes or len(payload) > maximum_bytes:
        raise _invalid("v0.1 child response payload is invalid.")
    response = _canonical_bytes_object(payload, "v0.1 child response")
    return _validate_v01_worker_response(
        response,
        request=request,
        artifact=artifact,
    )


def _validate_v01_worker_response(
    value: object,
    *,
    request: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("v0.1 worker response must be an object.")
    response = _canonical_mapping("v0.1 worker response", value)
    if set(response) != {
        "format",
        "schema_version",
        "runtime_result_envelope",
        "progress_events",
        "evidence_refs",
    }:
        raise _invalid("v0.1 child response fields are invalid.")
    if (
        response["format"] != V01_CHILD_RESPONSE_FORMAT
        or response["schema_version"] != "1.0"
    ):
        raise _invalid("v0.1 child response format is invalid.")
    envelope = _validate_runtime_envelope(
        response["runtime_result_envelope"],
        nsl_execution_id=request["nsl_execution_id"],
    )
    runtime = envelope["runtime_result"]
    if (
        runtime["skill_id"] != artifact["skill_id"]
        or runtime["skill_version"] != artifact["skill_version"]
        or runtime["semantic_hash"] != artifact["skill_semantic_hash"]
    ):
        raise _invalid("v0.1 child result does not match the verified artifact.")
    progress = _validate_progress_events(
        response["progress_events"],
        nsl_execution_id=request["nsl_execution_id"],
        skill_id=artifact["skill_id"],
        skill_version=artifact["skill_version"],
        runtime_status=runtime["status"],
    )
    refs = _canonical_refs(response["evidence_refs"])
    return {
        **response,
        "runtime_result_envelope": envelope,
        "progress_events": progress,
        "evidence_refs": refs,
    }


def _load_v01_public_api() -> object:
    try:
        return importlib.import_module("nsl.api")
    except ImportError as exc:
        raise _dependency("Configured NSL v0.1 package is unavailable.") from exc


def _validated_v01_public_api(api: object) -> object:
    progress = getattr(api, "InMemoryProgressSink", None)
    job_type = getattr(api, "SkillExecutionJob", None)
    worker_type = getattr(api, "SkillExecutionWorker", None)
    if (
        not callable(progress)
        or not isinstance(job_type, type)
        or not callable(getattr(job_type, "from_data", None))
        or not isinstance(worker_type, type)
    ):
        raise _dependency("Configured NSL v0.1 public API is incomplete.")
    return api


def _execute_v01_in_process_session(
    *,
    api: object,
    session_factory: Callable[..., V01WorkerSession],
    artifact_handle: str,
    job: Mapping[str, Any],
) -> dict[str, Any]:
    progress = api.InMemoryProgressSink()
    session = session_factory(artifact_handle, progress)
    worker = getattr(session, "worker", None)
    if not isinstance(worker, api.SkillExecutionWorker):
        raise _invalid("v0.1 in-process session returned an invalid worker.")
    evidence_reader = getattr(session, "evidence_refs", None)
    if not callable(evidence_reader):
        raise _invalid("v0.1 in-process session lacks an evidence bridge.")
    try:
        execution_job = api.SkillExecutionJob.from_data(job)
    except Exception as exc:
        raise _invalid("v0.1 in-process job contract is invalid.") from exc
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise _invalid("v0.1 in-process execution requires a synchronous worker loop.")
    envelope = asyncio.run(worker.execute(execution_job))
    to_data = getattr(envelope, "to_data", None)
    if not callable(to_data):
        raise _invalid("v0.1 in-process worker returned an invalid result envelope.")
    try:
        progress_events = [event.to_data() for event in progress.events]
        evidence_refs = list(evidence_reader())
        runtime_result_envelope = to_data()
    except Exception as exc:
        raise _invalid("v0.1 in-process evidence bridge is invalid.") from exc
    return {
        "format": V01_CHILD_RESPONSE_FORMAT,
        "schema_version": "1.0",
        "runtime_result_envelope": runtime_result_envelope,
        "progress_events": progress_events,
        "evidence_refs": evidence_refs,
    }


def _validate_runtime_envelope(
    value: object, *, nsl_execution_id: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "format",
        "schema_version",
        "runtime_result",
    }:
        raise _invalid("v0.1 runtime result envelope fields are invalid.")
    envelope = _canonical_mapping("v0.1 runtime result envelope", value)
    if (
        envelope["format"] != NSL_RESULT_FORMAT
        or envelope["schema_version"] != NSL_RESULT_SCHEMA_VERSION
    ):
        raise _invalid("v0.1 runtime result envelope format is invalid.")
    result = envelope["runtime_result"]
    result_fields = {
        "schema_version",
        "execution_id",
        "skill_id",
        "skill_version",
        "semantic_hash",
        "status",
        "completeness",
        "checks",
        "outputs",
        "resources",
        "error",
    }
    if not isinstance(result, Mapping) or set(result) != result_fields:
        raise _invalid("v0.1 runtime result fields are invalid.")
    if result["schema_version"] != "1.0" or result["execution_id"] != nsl_execution_id:
        raise _invalid("v0.1 runtime result identity is invalid.")
    _text("skill_id", result["skill_id"], 256)
    _text("skill_version", result["skill_version"], 256)
    _hash("semantic_hash", result["semantic_hash"])
    if result["status"] not in TERMINAL_RUNTIME_STATUSES:
        raise _invalid("v0.1 terminal envelope contains a non-terminal status.")
    if result["completeness"] not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
        raise _invalid("v0.1 runtime result completeness is invalid.")
    for field in ("checks", "outputs"):
        if not isinstance(result[field], list) or len(result[field]) > 10_000:
            raise _invalid(f"v0.1 runtime result {field} is invalid.")
    resources = result["resources"]
    if not isinstance(resources, Mapping) or set(resources) != {
        "tool_calls",
        "loop_iterations",
        "emitted_rows",
        "max_collection_size_seen",
    }:
        raise _invalid("v0.1 runtime resource summary is invalid.")
    for field, item in resources.items():
        _bounded_int(field, item, 0, 2_147_483_647)
    if result["error"] is not None and not isinstance(result["error"], Mapping):
        raise _invalid("v0.1 runtime error is invalid.")
    return envelope


def _validate_progress_events(
    value: object,
    *,
    nsl_execution_id: str,
    skill_id: str,
    skill_version: str,
    runtime_status: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise _invalid("v0.1 progress events must be a bounded non-empty array.")
    normalized: list[dict[str, Any]] = []
    for index, event in enumerate(value, start=1):
        fields = {
            "format",
            "schema_version",
            "execution_id",
            "sequence",
            "state",
            "skill_id",
            "skill_version",
            "runtime_status",
            "error_code",
        }
        if not isinstance(event, Mapping) or set(event) != fields:
            raise _invalid("v0.1 progress event fields are invalid.")
        event = _canonical_mapping("v0.1 progress event", event)
        if (
            event["format"] != NSL_PROGRESS_FORMAT
            or event["schema_version"] != NSL_PROGRESS_SCHEMA_VERSION
            or event["execution_id"] != nsl_execution_id
            or event["sequence"] != index
            or event["state"] not in PROGRESS_STATES
            or event["skill_id"] != skill_id
            or event["skill_version"] != skill_version
        ):
            raise _invalid("v0.1 progress event identity or sequence is invalid.")
        normalized.append(event)
    states = [event["state"] for event in normalized]
    if states[:3] != ["STARTED", "SKILL_RESOLVED", "RUNNING"]:
        raise _invalid("v0.1 progress lifecycle prefix is invalid.")
    expected_terminal = "COMPLETED" if runtime_status == "COMPLETED" else "FAILED"
    tail = normalized[-1]
    if tail["state"] != expected_terminal or tail["runtime_status"] != runtime_status:
        raise _invalid("v0.1 progress terminal state does not match the result.")
    if any(event["runtime_status"] is not None for event in normalized[:-1]):
        raise _invalid("v0.1 non-terminal progress cannot carry runtime status.")
    return normalized


def _failed_backend_run(
    *,
    request: Mapping[str, Any],
    artifact: Mapping[str, Any],
    attempt_no: int,
    started_at: str,
    completed_at: str,
    isolation_status: str,
    error_code: str,
    exit_code: object,
    retryable: bool,
    backend_profile: str = BACKEND_PROFILE,
) -> dict[str, Any]:
    record = {
        "schema_version": BACKEND_RUN_SCHEMA_VERSION,
        "tenant_id": request["tenant_id"],
        "executable_step_id": request["executable_step_id"],
        "nsl_execution_id": request["nsl_execution_id"],
        "business_operation_id": request["business_operation_id"],
        "attempt_no": attempt_no,
        "backend_profile": backend_profile,
        "isolation_status": isolation_status,
        "runtime_status": None,
        "runtime_result_envelope": None,
        "progress_events": [],
        "evidence_refs": [
            _backend_run_ref(request["nsl_execution_id"], attempt_no),
            f"AE:NSL_ISOLATION:{request['nsl_execution_id']}:{attempt_no}",
        ],
        "error_code": _text("error_code", error_code, 256),
        "exit_code": exit_code if type(exit_code) is int else None,
        "retryable": retryable,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    if artifact["skill_id"] != request["skill_id"]:
        raise _invalid("Failed backend evidence has mismatched Skill identity.")
    record["record_hash"] = semantic_sha256_hash_ref(record)
    return validate_nsl_backend_run(record)


def _inflate_context(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    occupied: set[tuple[str, ...]] = set()
    for entry in entries:
        parts = tuple(str(entry["path"]).split("."))
        if any(parts[:index] in occupied for index in range(1, len(parts))):
            raise _invalid("Runtime context paths cannot overlap.")
        if any(existing[: len(parts)] == parts for existing in occupied):
            raise _invalid("Runtime context paths cannot overlap.")
        cursor = root
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = entry["value"]
        occupied.add(parts)
    return root


def _backend_run_ref(nsl_execution_id: str, attempt_no: int) -> str:
    return f"AE:NSL_BACKEND_RUN:{nsl_execution_id}:{attempt_no}"


def _canonical_refs(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid("Evidence refs must be an array.")
    refs = [_text("evidence_ref", item, 512) for item in value]
    if len(refs) > 128 or len(set(refs)) != len(refs):
        raise _invalid("Evidence refs must be bounded and unique.")
    return sorted(refs)


def _backend_run_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tenant_id": record["tenant_id"],
        "nsl_execution_id": record["nsl_execution_id"],
        "attempt_no": record["attempt_no"],
        "executable_step_id": record["executable_step_id"],
        "business_operation_id": record["business_operation_id"],
        "isolation_status": record["isolation_status"],
        "runtime_status": record["runtime_status"],
        "record_hash": record["record_hash"],
        "record_json": canonical_json(record),
        "started_at": record["started_at"],
        "completed_at": record["completed_at"],
    }


def _backend_run_insert_sql(dialect_name: str) -> str:
    record_json = (
        "CAST(:record_json AS JSONB)"
        if dialect_name == "postgresql"
        else ":record_json"
    )
    return f"""
        INSERT INTO ae_nsl_backend_run (
            tenant_id, nsl_execution_id, attempt_no, executable_step_id,
            business_operation_id, isolation_status, runtime_status,
            record_hash, record_json, started_at, completed_at
        ) VALUES (
            :tenant_id, :nsl_execution_id, :attempt_no, :executable_step_id,
            :business_operation_id, :isolation_status, :runtime_status,
            :record_hash, {record_json}, :started_at, :completed_at
        ) ON CONFLICT DO NOTHING
    """


def _load_backend_run(
    session: Session, tenant_id: str, nsl_execution_id: str, attempt_no: int
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT record_json FROM ae_nsl_backend_run "
                "WHERE tenant_id = :tenant_id AND nsl_execution_id = :execution_id "
                "AND attempt_no = :attempt_no"
            ),
            {
                "tenant_id": tenant_id,
                "execution_id": nsl_execution_id,
                "attempt_no": attempt_no,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    value = row["record_json"]
    if isinstance(value, str):
        value = json.loads(value)
    return validate_nsl_backend_run(value)


def _canonical_bytes_object(value: object, name: str) -> dict[str, Any]:
    if type(value) is not bytes or not value or len(value) > MAX_BACKEND_PAYLOAD_BYTES:
        raise _invalid(f"{name} bytes are invalid.")
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid(f"{name} JSON is invalid.") from exc
    if not isinstance(decoded, Mapping):
        raise _invalid(f"{name} must be an object.")
    normalized = _canonical_mapping(name, decoded)
    if value != canonical_json(normalized).encode("utf-8"):
        raise _invalid(f"{name} must use canonical JSON.")
    return normalized


def _canonical_mapping(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{name} must be an object.")
    try:
        return json.loads(canonical_json(dict(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} must be canonical JSON.") from exc


def _clock_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise _invalid("NSL backend clock returned an invalid value.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise _invalid("NSL backend clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an RFC3339 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _uuid(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be a UUID.")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a UUID.") from exc
    if str(parsed) != value:
        raise _invalid(f"{field} must be a canonical UUID.")
    return value


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a lowercase SHA-256 reference.") from exc


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _invalid(f"{field} must be a non-empty bounded string.")
    return value.strip()


def _bounded_int(field: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(f"{field} must be between {minimum} and {maximum}.")
    return value


def _dialect_name(session: Session) -> str:
    return session.get_bind().dialect.name


def _invalid(detail: str) -> NSLReadBackendError:
    return NSLReadBackendError("ae.nsl_read_backend_invalid", detail)


def _dependency(detail: str) -> NSLReadBackendError:
    return NSLReadBackendError("ae.nsl_read_backend_unavailable", detail)
