from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    JobQueue,
    JobQueueError,
    build_common_job,
    build_subject_ref,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_cx.remediation_execution_boundary import (
    RemediationExecutionBoundaryError,
    assert_cx_remediation_execution_payload_redaction_safe,
    remediation_action_executable_by_cx,
    remediation_lineage_type_for_action,
)


CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION = (
    "cx_remediation_execution_request.v1"
)
CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION = (
    "cx_remediation_execution_result.v1"
)
CX_REMEDIATION_EXECUTION_ACCEPTED_STATUS = "ACCEPTED"
CX_REMEDIATION_EXECUTION_JOB_TYPE = "cx.remediation_execution"
PROVIDER_BOUNDARY = "cx_to_mo_service_api_only"
REDACTION_EXCLUDED_FIELDS = (
    "raw_prompt",
    "messages",
    "source_text",
    "output_text",
    "raw_output",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "storage_path",
    "api_key",
)


class ParentGenerationStore(Protocol):
    def get(self, cx_generation_id: str) -> dict[str, Any] | None:
        ...


class RemediationExecutionStoreProtocol(Protocol):
    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        ...

    def list_for_parent(self, parent_cx_generation_id: str) -> list[dict[str, Any]]:
        ...


@dataclass
class RemediationExecutionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_ids_by_parent: dict[str, list[str]] = field(default_factory=dict)

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        action_id = record["remediation_action_id"]
        previous = self.records.get(action_id)
        if previous is not None:
            self._remove_parent_index(previous["parent_cx_generation_id"], action_id)
        self.records[action_id] = record
        parent_ids = self.action_ids_by_parent.setdefault(
            record["parent_cx_generation_id"],
            [],
        )
        if action_id not in parent_ids:
            parent_ids.append(action_id)
        return record

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        return self.records.get(remediation_action_id)

    def list_for_parent(self, parent_cx_generation_id: str) -> list[dict[str, Any]]:
        return [
            self.records[action_id]
            for action_id in self.action_ids_by_parent.get(parent_cx_generation_id, [])
            if action_id in self.records
        ]

    def _remove_parent_index(self, parent_cx_generation_id: str, action_id: str) -> None:
        ids = self.action_ids_by_parent.get(parent_cx_generation_id, [])
        self.action_ids_by_parent[parent_cx_generation_id] = [
            existing_id for existing_id in ids if existing_id != action_id
        ]


class SqlAlchemyRemediationExecutionStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        source_kind: str = "postgres-write",
        database_env: str | None = None,
        redacted_database_url: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.source_kind = source_kind
        self.database_env = database_env
        self.redacted_database_url = redacted_database_url

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        record_to_store = dict(record)
        try:
            self._run_in_transaction(
                lambda session: session.execute(
                    text(_remediation_execution_upsert_sql(session)),
                    _remediation_execution_persistence_params(record_to_store),
                )
            )
            return record
        except SQLAlchemyError as exc:
            raise _remediation_execution_store_unavailable() from exc

    def get(self, remediation_action_id: str) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    text(_remediation_execution_select_sql(
                        "remediation_action_id = :remediation_action_id"
                    )),
                    {"remediation_action_id": remediation_action_id},
                ).mappings().first()
                return _remediation_execution_record_from_row(row)
        except SQLAlchemyError as exc:
            raise _remediation_execution_store_unavailable() from exc

    def list_for_parent(self, parent_cx_generation_id: str) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.execute(
                    text(
                        _remediation_execution_select_sql(
                            "parent_cx_generation_id = :parent_cx_generation_id"
                        )
                        + " ORDER BY updated_at DESC, remediation_action_id ASC"
                    ),
                    {"parent_cx_generation_id": parent_cx_generation_id},
                ).mappings().all()
                return [
                    record
                    for row in rows
                    if (record := _remediation_execution_record_from_row(row))
                    is not None
                ]
        except SQLAlchemyError as exc:
            raise _remediation_execution_store_unavailable() from exc

    def _run_in_transaction(self, operation: Any) -> Any:
        session = self._session_factory()
        try:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise
        finally:
            session.close()


DEFAULT_REMEDIATION_EXECUTION_STORE = RemediationExecutionStore()


@dataclass(frozen=True)
class RemediationExecutionError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def register_remediation_execution_routes(
    app: FastAPI,
    *,
    generation_store: ParentGenerationStore,
    execution_store: RemediationExecutionStoreProtocol | None = None,
    job_queue: JobQueue | None = None,
) -> None:
    selected_execution_store = execution_store or DEFAULT_REMEDIATION_EXECUTION_STORE

    @app.post(
        "/api/v1/generations/{cx_generation_id}/remediation-executions",
        response_model=None,
        status_code=202,
    )
    def create_remediation_execution(
        cx_generation_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            validated_payload = validate_cx_remediation_execution_request(payload)
            parent_id = required_text(
                validated_payload,
                "parent_cx_generation_id",
            )
            if parent_id != cx_generation_id:
                raise RemediationExecutionError(
                    status_code=400,
                    error_code="cx.remediation_execution_parent_mismatch",
                    detail=(
                        "Remediation execution path generation id does not match "
                        "the request parent_cx_generation_id."
                    ),
                    retryable=False,
                )
            parent_record = generation_store.get(cx_generation_id)
            if parent_record is None:
                raise RemediationExecutionError(
                    status_code=404,
                    error_code="cx.remediation_execution_parent_not_found",
                    detail=(
                        "Parent CX generation record was not found: "
                        f"{cx_generation_id}"
                    ),
                    retryable=False,
                )
            result = build_cx_remediation_execution_result(
                validated_payload,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
            selected_execution_store.save(result)
            if job_queue is not None:
                enqueue_remediation_execution_job(
                    job_queue,
                    execution_record=result,
                    request_payload=validated_payload,
                )
            return JSONResponse(status_code=202, content=result)
        except RemediationExecutionError as exc:
            return _remediation_execution_problem_response(request, exc)


def validate_cx_remediation_execution_request(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        assert_cx_remediation_execution_payload_redaction_safe(payload)
    except RemediationExecutionBoundaryError as exc:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_sensitive_payload",
            detail=str(exc),
            retryable=False,
        ) from exc

    if (
        payload.get("request_schema_version")
        != CX_REMEDIATION_EXECUTION_REQUEST_SCHEMA_VERSION
    ):
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_request_schema_invalid",
            detail="CX remediation execution request schema version is invalid.",
            retryable=False,
        )

    action_type = required_text(payload, "action_type")
    if not remediation_action_executable_by_cx(action_type):
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_action_not_executable",
            detail=f"Remediation action is not executable by CX: {action_type}",
            retryable=False,
        )

    lineage_type = required_text(payload, "lineage_type")
    expected_lineage_type = remediation_lineage_type_for_action(action_type)
    if lineage_type != expected_lineage_type:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_lineage_invalid",
            detail=(
                "Remediation execution lineage_type does not match action_type: "
                f"{action_type}"
            ),
            retryable=False,
        )

    policy = _mapping(payload.get("execution_policy"))
    if policy.get("parent_generation_mutation_allowed") is not False:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_parent_mutation_forbidden",
            detail="CX remediation execution cannot mutate the parent generation.",
            retryable=False,
        )
    if policy.get("provider_boundary") != PROVIDER_BOUNDARY:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_provider_boundary_invalid",
            detail="CX remediation execution must call MO service APIs only.",
            retryable=False,
        )

    evidence = _mapping(payload.get("evidence"))
    if evidence.get("raw_evidence_stored") is not False:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_evidence_invalid",
            detail="CX remediation execution requires raw_evidence_stored=false.",
            retryable=False,
        )

    required_text(payload, "remediation_action_id")
    required_text(payload, "parent_cx_generation_id")
    required_text(payload, "trace_id")
    required_text(payload, "request_id")
    return dict(payload)


def build_cx_remediation_execution_result(
    payload: Mapping[str, Any],
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = created_at or _utc_now()
    return {
        "result_schema_version": CX_REMEDIATION_EXECUTION_RESULT_SCHEMA_VERSION,
        "remediation_action_id": required_text(payload, "remediation_action_id"),
        "parent_cx_generation_id": required_text(payload, "parent_cx_generation_id"),
        "repair_cx_generation_id": None,
        "tenant_id": optional_text(payload.get("tenant_id")),
        "trace_id": trace_id or required_text(payload, "trace_id"),
        "request_id": request_id or required_text(payload, "request_id"),
        "action_type": required_text(payload, "action_type"),
        "lineage_type": required_text(payload, "lineage_type"),
        "execution_status": CX_REMEDIATION_EXECUTION_ACCEPTED_STATUS,
        "result_ref": None,
        "failure": None,
        "redaction_summary": {
            "raw_content_included": False,
            "prompt_text_included": False,
            "evidence_text_included": False,
            "provider_detail_included": False,
            "excluded_fields": list(REDACTION_EXCLUDED_FIELDS),
        },
        "created_at": now,
        "updated_at": now,
    }


def build_remediation_execution_job(
    *,
    execution_record: Mapping[str, Any],
    request_payload: Mapping[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    from nex_cx.remediation_execution_planning import (
        build_remediation_execution_worker_plan,
    )

    record = dict(execution_record)
    payload = dict(request_payload)
    plan = build_remediation_execution_worker_plan(
        record,
        planned_at=created_at or optional_text(record.get("created_at")),
    )
    action_id = required_text(record, "remediation_action_id")
    parent_id = required_text(record, "parent_cx_generation_id")
    job = build_common_job(
        job_id=remediation_execution_job_id(action_id),
        job_type=CX_REMEDIATION_EXECUTION_JOB_TYPE,
        trace_id=required_text(record, "trace_id"),
        request_id=required_text(record, "request_id"),
        subject_ref=build_subject_ref("cx.remediation_execution", action_id),
        idempotency_key=required_text(payload, "idempotency_key"),
        max_attempts=1,
        retryable=True,
        links={
            "parent_generation": f"/api/v1/generations/{parent_id}",
            "remediation_execution": (
                f"/api/v1/generations/{parent_id}/remediation-executions"
            ),
        },
        created_at=created_at or optional_text(record.get("created_at")),
    )
    job["payload"] = {
        "payload_schema_version": "cx_remediation_execution_job_payload.v1",
        "remediation_action_id": action_id,
        "parent_cx_generation_id": parent_id,
        "root_cx_generation_id": plan["root_cx_generation_id"],
        "tenant_id": record.get("tenant_id"),
        "trace_id": record["trace_id"],
        "request_id": record["request_id"],
        "action_type": record["action_type"],
        "lineage_type": record["lineage_type"],
        "attempt_no": plan["attempt_no"],
        "reason_codes": list(payload.get("reason_codes", [])),
        "source_refs": _safe_source_refs(payload.get("source_refs")),
        "evidence_hashes": _safe_evidence_hashes(payload.get("evidence")),
        "execution_policy": {
            "parent_generation_mutation_allowed": False,
            "retrieval_package_policy": plan["retrieval_package_policy"],
            "prompt_package_policy": plan["prompt_package_policy"],
            "provider_boundary": PROVIDER_BOUNDARY,
        },
        "worker_plan": plan,
        "redaction_summary": dict(record.get("redaction_summary", {})),
    }
    assert_cx_remediation_execution_payload_redaction_safe(job)
    return job


def enqueue_remediation_execution_job(
    queue: JobQueue,
    *,
    execution_record: Mapping[str, Any],
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return queue.enqueue(
            build_remediation_execution_job(
                execution_record=execution_record,
                request_payload=request_payload,
            )
        )
    except JobQueueError as exc:
        raise RemediationExecutionError(
            status_code=exc.status_code,
            error_code="cx.remediation_execution_job_admission_failed",
            detail=exc.detail,
            retryable=exc.status_code >= 500,
        ) from exc


def remediation_execution_job_id(remediation_action_id: str) -> str:
    action_id = optional_text(remediation_action_id)
    if action_id is None:
        raise RemediationExecutionError(
            status_code=422,
            error_code="cx.remediation_execution_remediation_action_id_required",
            detail="CX remediation execution requires remediation_action_id.",
            retryable=False,
        )
    return str(uuid5(NAMESPACE_URL, f"cx-remediation-execution-job:{action_id}"))


def _safe_source_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _safe_evidence_hashes(value: Any) -> list[str]:
    evidence = _mapping(value)
    hashes = evidence.get("evidence_hashes", [])
    if not isinstance(hashes, list):
        return []
    return [str(item) for item in hashes]


def required_text(payload: Mapping[str, Any], key: str) -> str:
    value = optional_text(payload.get(key))
    if value is None:
        raise RemediationExecutionError(
            status_code=422,
            error_code=f"cx.remediation_execution_{key}_required",
            detail=f"CX remediation execution requires {key}.",
            retryable=False,
        )
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None
    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _remediation_execution_problem_response(
    request: Request,
    exc: RemediationExecutionError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="CX remediation execution request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri=(
            "https://nex-platform.local/problems/"
            "cx-remediation-execution-request-failed"
        ),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _remediation_execution_upsert_sql(session: Session) -> str:
    result_ref = _json_sql_expression(session, "result_ref")
    failure = _json_sql_expression(session, "failure")
    redaction_summary = _json_sql_expression(session, "redaction_summary")
    metadata = _json_sql_expression(session, "metadata")
    return f"""
        INSERT INTO cx_remediation_execution_attempts (
            remediation_action_id,
            result_schema_version,
            parent_cx_generation_id,
            root_cx_generation_id,
            repair_cx_generation_id,
            tenant_id,
            trace_id,
            request_id,
            action_type,
            lineage_type,
            execution_status,
            attempt_no,
            result_ref,
            failure,
            redaction_summary,
            metadata,
            created_at,
            updated_at
        )
        VALUES (
            :remediation_action_id,
            :result_schema_version,
            :parent_cx_generation_id,
            :root_cx_generation_id,
            :repair_cx_generation_id,
            :tenant_id,
            :trace_id,
            :request_id,
            :action_type,
            :lineage_type,
            :execution_status,
            :attempt_no,
            {result_ref},
            {failure},
            {redaction_summary},
            {metadata},
            :created_at,
            :updated_at
        )
        ON CONFLICT (remediation_action_id) DO UPDATE SET
            result_schema_version = excluded.result_schema_version,
            parent_cx_generation_id = excluded.parent_cx_generation_id,
            root_cx_generation_id = excluded.root_cx_generation_id,
            repair_cx_generation_id = excluded.repair_cx_generation_id,
            tenant_id = excluded.tenant_id,
            trace_id = excluded.trace_id,
            request_id = excluded.request_id,
            action_type = excluded.action_type,
            lineage_type = excluded.lineage_type,
            execution_status = excluded.execution_status,
            attempt_no = excluded.attempt_no,
            result_ref = excluded.result_ref,
            failure = excluded.failure,
            redaction_summary = excluded.redaction_summary,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _remediation_execution_select_sql(where_clause: str) -> str:
    return f"""
        SELECT
            remediation_action_id,
            result_schema_version,
            parent_cx_generation_id,
            root_cx_generation_id,
            repair_cx_generation_id,
            tenant_id,
            trace_id,
            request_id,
            action_type,
            lineage_type,
            execution_status,
            attempt_no,
            result_ref,
            failure,
            redaction_summary,
            metadata,
            created_at,
            updated_at
        FROM cx_remediation_execution_attempts
        WHERE {where_clause}
    """


def _remediation_execution_persistence_params(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "remediation_action_id": required_text(record, "remediation_action_id"),
        "result_schema_version": required_text(record, "result_schema_version"),
        "parent_cx_generation_id": required_text(record, "parent_cx_generation_id"),
        "root_cx_generation_id": (
            optional_text(record.get("root_cx_generation_id"))
            or required_text(record, "parent_cx_generation_id")
        ),
        "repair_cx_generation_id": optional_text(record.get("repair_cx_generation_id")),
        "tenant_id": optional_text(record.get("tenant_id")),
        "trace_id": required_text(record, "trace_id"),
        "request_id": required_text(record, "request_id"),
        "action_type": required_text(record, "action_type"),
        "lineage_type": required_text(record, "lineage_type"),
        "execution_status": required_text(record, "execution_status"),
        "attempt_no": _positive_int(record.get("attempt_no"), default=1),
        "result_ref": _json_dumps_or_none(record.get("result_ref")),
        "failure": _json_dumps_or_none(record.get("failure")),
        "redaction_summary": _json_dumps(record.get("redaction_summary", {})),
        "metadata": _json_dumps(record.get("metadata", {})),
        "created_at": optional_text(record.get("created_at")) or _utc_now(),
        "updated_at": optional_text(record.get("updated_at")) or _utc_now(),
    }


def _remediation_execution_record_from_row(
    row: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "result_schema_version": row["result_schema_version"],
        "remediation_action_id": row["remediation_action_id"],
        "parent_cx_generation_id": row["parent_cx_generation_id"],
        "root_cx_generation_id": row["root_cx_generation_id"],
        "repair_cx_generation_id": row["repair_cx_generation_id"],
        "tenant_id": row["tenant_id"],
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "action_type": row["action_type"],
        "lineage_type": row["lineage_type"],
        "execution_status": row["execution_status"],
        "attempt_no": row["attempt_no"],
        "result_ref": _json_loads(row["result_ref"], default=None),
        "failure": _json_loads(row["failure"], default=None),
        "redaction_summary": _json_loads(row["redaction_summary"], default={}),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _json_sql_expression(session: Session, param_name: str) -> str:
    if _dialect_name(session) == "postgresql":
        return f"CAST(:{param_name} AS JSONB)"
    return f":{param_name}"


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_dumps_or_none(value: Any) -> str | None:
    return None if value is None else _json_dumps(value)


def _json_loads(value: Any, *, default: Any) -> Any:
    if value is None:
        return deepcopy(default)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(default)


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value


def _remediation_execution_store_unavailable() -> RemediationExecutionError:
    return RemediationExecutionError(
        status_code=503,
        error_code="cx.remediation_execution_store_unavailable",
        detail="CX remediation execution store is unavailable.",
        retryable=True,
    )
