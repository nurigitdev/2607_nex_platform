from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from nex_ag.generation_remediation_execution import (
    TARGET_STATUS_BY_CX_EXECUTION_STATUS,
)
from nex_ag.operations import OperationQueryOptions, build_operation_query_options


AG_REMEDIATION_EXECUTION_OPERATIONS_PROJECTION_SCHEMA_VERSION = (
    "ag_remediation_execution_operations_projection.v1"
)
AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID = "nex-ag"
CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID = "nex-cx"
DEFAULT_REMEDIATION_EXECUTION_OPERATION_LIMIT = 50
MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT = 500
AG_TASK_TERMINAL_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")
CX_EXECUTION_TERMINAL_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED")


class RemediationTaskOperationsStore(Protocol):
    source_kind: str
    database_env: str | None
    redacted_database_url: str | None

    def list_recent(
        self,
        *,
        limit: int = MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        ...


class RemediationExecutionOperationsStore(Protocol):
    source_kind: str
    database_env: str | None
    redacted_database_url: str | None

    def list_remediation_executions(
        self,
        *,
        parent_cx_generation_id: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        remediation_action_id: str | None = None,
        limit: int = MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class RemediationExecutionOperationsError(Exception):
    error_code: str
    detail: str
    status_code: int = 503

    def __str__(self) -> str:
        return self.detail


@dataclass
class InMemoryRemediationExecutionOperationsStore:
    records: list[dict[str, Any]] = field(default_factory=list)
    source_kind: str = "memory"
    database_env: str | None = None
    redacted_database_url: str | None = None

    def list_remediation_executions(
        self,
        *,
        parent_cx_generation_id: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        remediation_action_id: str | None = None,
        limit: int = MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for record in self.records:
            if (
                parent_cx_generation_id is not None
                and record.get("parent_cx_generation_id") != parent_cx_generation_id
            ):
                continue
            if (
                execution_status is not None
                and record.get("execution_status") != execution_status
            ):
                continue
            if trace_id is not None and record.get("trace_id") != trace_id:
                continue
            if request_id is not None and record.get("request_id") != request_id:
                continue
            if (
                remediation_action_id is not None
                and record.get("remediation_action_id") != remediation_action_id
            ):
                continue
            filtered.append(deepcopy(record))
        return filtered[:limit]


class SqlAlchemyRemediationExecutionOperationsStore:
    source_kind = "postgres-read"

    def __init__(
        self,
        session_factory: Any,
        *,
        database_env: str | None = None,
        redacted_database_url: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.database_env = database_env
        self.redacted_database_url = redacted_database_url

    def list_remediation_executions(
        self,
        *,
        parent_cx_generation_id: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        remediation_action_id: str | None = None,
        limit: int = MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if parent_cx_generation_id is not None:
            conditions.append("parent_cx_generation_id = :parent_cx_generation_id")
            params["parent_cx_generation_id"] = parent_cx_generation_id
        if execution_status is not None:
            conditions.append("execution_status = :execution_status")
            params["execution_status"] = execution_status
        if trace_id is not None:
            conditions.append("trace_id = :trace_id")
            params["trace_id"] = trace_id
        if request_id is not None:
            conditions.append("request_id = :request_id")
            params["request_id"] = request_id
        if remediation_action_id is not None:
            conditions.append("remediation_action_id = :remediation_action_id")
            params["remediation_action_id"] = remediation_action_id
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = text(
            f"""
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
            {where_clause}
            ORDER BY updated_at DESC, remediation_action_id ASC
            LIMIT :limit
            """
        )
        try:
            with self._session_factory() as session:
                rows = session.execute(query, params).mappings().all()
        except SQLAlchemyError as exc:
            raise RemediationExecutionOperationsError(
                error_code="ag.remediation_execution_source_unavailable",
                detail="CX remediation execution operations source could not be read.",
            ) from exc
        return [_execution_record_from_row(row) for row in rows]


def build_remediation_execution_operations_projection(
    *,
    task_stores: Mapping[str, RemediationTaskOperationsStore],
    execution_stores: Mapping[str, RemediationExecutionOperationsStore],
    cx_generation_id: str | None = None,
    remediation_action_id: str | None = None,
    action_status: str | None = None,
    execution_status: str | None = None,
    trace_id: str | None = None,
    request_id: str | None = None,
    query_options: OperationQueryOptions | None = None,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    options = query_options or build_operation_query_options(
        limit=DEFAULT_REMEDIATION_EXECUTION_OPERATION_LIMIT
    )
    task_source = _read_task_records(
        task_stores.get(AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID),
        action_status=action_status,
        cx_generation_id=cx_generation_id,
        trace_id=trace_id,
        request_id=request_id,
        remediation_action_id=remediation_action_id,
    )
    execution_source = _read_execution_records(
        execution_stores.get(CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID),
        cx_generation_id=cx_generation_id,
        execution_status=execution_status,
        trace_id=trace_id,
        request_id=request_id,
        remediation_action_id=remediation_action_id,
    )
    items = _merge_task_and_execution_records(
        task_source["records"],
        execution_source["records"],
    )
    if action_status is not None:
        items = [item for item in items if item.get("task_status") == action_status]
    if execution_status is not None:
        items = [
            item for item in items if item.get("execution_status") == execution_status
        ]
    items = _filter_operations_by_time(items, options)
    page = _apply_operation_query_options(items, options)
    source_statuses = {
        AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: task_source["source_status"],
        CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID: execution_source["source_status"],
    }
    projection_status = (
        "DEGRADED"
        if any(
            source["status"] in {"NOT_CONFIGURED", "UNAVAILABLE"}
            for source in source_statuses.values()
        )
        else "READY"
    )
    projection = {
        "projection_schema_version": (
            AG_REMEDIATION_EXECUTION_OPERATIONS_PROJECTION_SCHEMA_VERSION
        ),
        "projection_status": projection_status,
        "checked_at": _utc_now(),
        "filters": {
            "cx_generation_id": cx_generation_id,
            "remediation_action_id": remediation_action_id,
            "action_status": action_status,
            "execution_status": execution_status,
            "trace_id": trace_id,
            "request_id": request_id,
            **options.to_filter_dict(),
        },
        "operations": page["items"],
        "summary": summarize_remediation_execution_operations(page["items"]),
        "source_statuses": source_statuses,
        "pagination": page["pagination"],
        "redaction_summary": _remediation_execution_operations_redaction_summary(),
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def summarize_remediation_execution_operations(
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    by_task_status = _count_by(operations, "task_status")
    by_execution_status = _count_by(operations, "execution_status")
    return {
        "total": len(operations),
        "by_task_status": by_task_status,
        "by_execution_status": by_execution_status,
        "sync_required_count": sum(
            1 for item in operations if item["status_sync_state"] == "SYNC_REQUIRED"
        ),
        "missing_execution_count": sum(
            1 for item in operations if item["execution_status"] is None
        ),
        "orphan_execution_count": sum(
            1 for item in operations if item["task_status"] is None
        ),
        "failed_execution_count": by_execution_status.get("FAILED", 0),
        "attention_required_count": sum(
            1 for item in operations if item["attention_required"] is True
        ),
    }


def _read_task_records(
    store: RemediationTaskOperationsStore | None,
    *,
    action_status: str | None,
    cx_generation_id: str | None,
    trace_id: str | None,
    request_id: str | None,
    remediation_action_id: str | None,
) -> dict[str, Any]:
    if store is None:
        return {
            "records": [],
            "source_status": _source_status(
                service_id=AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
                source_kind="none",
                record_count=0,
                status="NOT_CONFIGURED",
            ),
        }
    try:
        records = store.list_recent(
            limit=MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT
        )
    except Exception as exc:
        error = _operations_error_from_exception(
            exc,
            default_code="ag.remediation_task_source_unavailable",
            default_detail="AG remediation task operations source could not be read.",
        )
        return {
            "records": [],
            "source_status": _source_status(
                service_id=AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
                store=store,
                record_count=0,
                status="UNAVAILABLE",
                error=error,
            ),
        }
    filtered = [
        dict(record)
        for record in records
        if _matches_common_filters(
            record,
            cx_generation_id=cx_generation_id,
            trace_id=trace_id,
            request_id=request_id,
            remediation_action_id=remediation_action_id,
        )
        and (action_status is None or record.get("action_status") == action_status)
    ]
    return {
        "records": filtered,
        "source_status": _source_status(
            service_id=AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
            store=store,
            record_count=len(filtered),
            status="READY",
        ),
    }


def _read_execution_records(
    store: RemediationExecutionOperationsStore | None,
    *,
    cx_generation_id: str | None,
    execution_status: str | None,
    trace_id: str | None,
    request_id: str | None,
    remediation_action_id: str | None,
) -> dict[str, Any]:
    if store is None:
        return {
            "records": [],
            "source_status": _source_status(
                service_id=CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
                source_kind="none",
                record_count=0,
                status="NOT_CONFIGURED",
            ),
        }
    try:
        records = store.list_remediation_executions(
            parent_cx_generation_id=cx_generation_id,
            execution_status=execution_status,
            trace_id=trace_id,
            request_id=request_id,
            remediation_action_id=remediation_action_id,
            limit=MAX_REMEDIATION_EXECUTION_OPERATION_SCAN_LIMIT,
        )
    except RemediationExecutionOperationsError as exc:
        return {
            "records": [],
            "source_status": _source_status(
                service_id=CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
                store=store,
                record_count=0,
                status="UNAVAILABLE",
                error=exc,
            ),
        }
    return {
        "records": records,
        "source_status": _source_status(
            service_id=CX_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
            store=store,
            record_count=len(records),
            status="READY",
        ),
    }


def _merge_task_and_execution_records(
    task_records: list[dict[str, Any]],
    execution_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tasks_by_id = {
        str(task["remediation_action_id"]): task
        for task in task_records
        if task.get("remediation_action_id") is not None
    }
    executions_by_id = {
        str(execution["remediation_action_id"]): execution
        for execution in execution_records
        if execution.get("remediation_action_id") is not None
    }
    action_ids = sorted(set(tasks_by_id) | set(executions_by_id))
    return [
        _project_remediation_execution_operation(
            task=tasks_by_id.get(action_id),
            execution=executions_by_id.get(action_id),
        )
        for action_id in action_ids
    ]


def _project_remediation_execution_operation(
    *,
    task: Mapping[str, Any] | None,
    execution: Mapping[str, Any] | None,
) -> dict[str, Any]:
    action_id = _first_text(task, execution, key="remediation_action_id")
    cx_generation_id = _first_text(
        task,
        execution,
        task_key="cx_generation_id",
        execution_key="parent_cx_generation_id",
    )
    task_status = str(task["action_status"]) if task is not None else None
    execution_status = (
        str(execution["execution_status"]) if execution is not None else None
    )
    target_task_status = _target_task_status(execution_status)
    status_sync_state = _status_sync_state(
        task_status=task_status,
        execution_status=execution_status,
        target_task_status=target_task_status,
    )
    operation_timestamp = _max_timestamp(
        _optional_value(task, "updated_at"),
        _optional_value(execution, "updated_at"),
    )
    operation = {
        "service_id": AG_REMEDIATION_EXECUTION_SOURCE_SERVICE_ID,
        "operation_type": "remediation_execution",
        "operation_timestamp": operation_timestamp,
        "remediation_action_id": action_id,
        "cx_generation_id": cx_generation_id,
        "trace_id": _first_text(task, execution, key="trace_id"),
        "request_id": _first_text(task, execution, key="request_id"),
        "tenant_id": _first_text(task, execution, key="tenant_id"),
        "action_type": _first_text(task, execution, key="action_type"),
        "priority": _optional_value(task, "priority"),
        "task_status": task_status,
        "execution_status": execution_status,
        "target_task_status": target_task_status,
        "status_sync_state": status_sync_state,
        "attention_required": _attention_required(
            task_status=task_status,
            execution_status=execution_status,
            status_sync_state=status_sync_state,
        ),
        "attempt_no": _int_value(_optional_value(execution, "attempt_no")),
        "lineage_type": _optional_value(execution, "lineage_type"),
        "repair_cx_generation_id": _optional_value(
            execution,
            "repair_cx_generation_id",
        ),
        "result_ref": _safe_result_ref(task, execution),
        "failure": _safe_failure_summary(execution),
        "owner_ref": deepcopy(_mapping_value(_optional_value(task, "owner_ref"))),
        "reason_codes": _string_list(_optional_value(task, "reason_codes")),
        "evidence_hash_count": len(
            _string_list(
                _mapping_value(_optional_value(task, "evidence")).get(
                    "evidence_hashes"
                )
            )
        ),
        "source_ref_count": len(_list_value(_optional_value(task, "source_refs"))),
        "task_updated_at": _timestamp_to_wire_or_none(_optional_value(task, "updated_at")),
        "execution_updated_at": _timestamp_to_wire_or_none(
            _optional_value(execution, "updated_at")
        ),
        "created_at": _timestamp_to_wire_or_none(
            _optional_value(task, "created_at")
            or _optional_value(execution, "created_at")
        ),
        "redaction_summary": _remediation_execution_operations_redaction_summary(),
    }
    return operation


def _target_task_status(execution_status: str | None) -> str | None:
    if execution_status is None:
        return None
    return TARGET_STATUS_BY_CX_EXECUTION_STATUS.get(execution_status)


def _status_sync_state(
    *,
    task_status: str | None,
    execution_status: str | None,
    target_task_status: str | None,
) -> str:
    if task_status is None:
        return "ORPHAN_EXECUTION"
    if execution_status is None:
        return "NO_EXECUTION"
    if target_task_status is None:
        return "UNKNOWN_EXECUTION_STATUS"
    if task_status == target_task_status:
        return "IN_SYNC"
    if task_status in AG_TASK_TERMINAL_STATUSES:
        return "TERMINAL_TASK_DIVERGED"
    return "SYNC_REQUIRED"


def _attention_required(
    *,
    task_status: str | None,
    execution_status: str | None,
    status_sync_state: str,
) -> bool:
    return (
        task_status in {"FAILED"}
        or execution_status in {"FAILED", "CANCELLED"}
        or status_sync_state
        in {"SYNC_REQUIRED", "ORPHAN_EXECUTION", "UNKNOWN_EXECUTION_STATUS"}
    )


def _source_status(
    *,
    service_id: str,
    record_count: int,
    status: str,
    store: Any | None = None,
    source_kind: str | None = None,
    error: RemediationExecutionOperationsError | None = None,
) -> dict[str, Any]:
    source = {
        "status": status,
        "service_id": service_id,
        "source_kind": source_kind or getattr(store, "source_kind", "none"),
        "record_count": record_count,
        "database_env": getattr(store, "database_env", None),
        "redacted_database_url": getattr(store, "redacted_database_url", None),
    }
    if error is not None:
        source["error_code"] = error.error_code
        source["detail"] = error.detail
    return source


def _operations_error_from_exception(
    exc: Exception,
    *,
    default_code: str,
    default_detail: str,
) -> RemediationExecutionOperationsError:
    return RemediationExecutionOperationsError(
        error_code=str(getattr(exc, "error_code", default_code)),
        detail=str(getattr(exc, "detail", default_detail)),
        status_code=int(getattr(exc, "status_code", 503)),
    )


def _matches_common_filters(
    record: Mapping[str, Any],
    *,
    cx_generation_id: str | None,
    trace_id: str | None,
    request_id: str | None,
    remediation_action_id: str | None,
) -> bool:
    if cx_generation_id is not None and record.get("cx_generation_id") != cx_generation_id:
        return False
    if trace_id is not None and record.get("trace_id") != trace_id:
        return False
    if request_id is not None and record.get("request_id") != request_id:
        return False
    if (
        remediation_action_id is not None
        and record.get("remediation_action_id") != remediation_action_id
    ):
        return False
    return True


def _filter_operations_by_time(
    operations: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> list[dict[str, Any]]:
    since_dt = _parse_timestamp(options.since) if options.since is not None else None
    until_dt = _parse_timestamp(options.until) if options.until is not None else None
    filtered = []
    for operation in operations:
        observed_at = _parse_timestamp(str(operation["operation_timestamp"]))
        if since_dt is not None and observed_at < since_dt:
            continue
        if until_dt is not None and observed_at > until_dt:
            continue
        filtered.append(operation)
    return filtered


def _apply_operation_query_options(
    operations: list[dict[str, Any]],
    options: OperationQueryOptions,
) -> dict[str, Any]:
    reverse = options.sort == "desc"
    sorted_operations = sorted(
        operations,
        key=lambda item: (
            _parse_timestamp(str(item["operation_timestamp"])),
            str(item["remediation_action_id"]),
        ),
        reverse=reverse,
    )
    page_items = sorted_operations[options.offset : options.offset + options.limit]
    return {
        "items": page_items,
        "pagination": options.pagination(
            total=len(sorted_operations),
            returned=len(page_items),
        ),
    }


def _execution_record_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "remediation_action_id": str(row["remediation_action_id"]),
        "result_schema_version": row["result_schema_version"],
        "parent_cx_generation_id": str(row["parent_cx_generation_id"]),
        "root_cx_generation_id": str(row["root_cx_generation_id"]),
        "repair_cx_generation_id": _optional_string(row["repair_cx_generation_id"]),
        "tenant_id": _optional_string(row["tenant_id"]),
        "trace_id": row["trace_id"],
        "request_id": row["request_id"],
        "action_type": row["action_type"],
        "lineage_type": row["lineage_type"],
        "execution_status": row["execution_status"],
        "attempt_no": _int_value(row["attempt_no"]),
        "result_ref": _json_loads(row["result_ref"], default=None),
        "failure": _json_loads(row["failure"], default=None),
        "redaction_summary": _json_loads(row["redaction_summary"], default={}),
        "metadata": _json_loads(row["metadata"], default={}),
        "created_at": _timestamp_to_wire(row["created_at"]),
        "updated_at": _timestamp_to_wire(row["updated_at"]),
    }


def _safe_result_ref(
    task: Mapping[str, Any] | None,
    execution: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    execution_ref = _mapping_value(_optional_value(execution, "result_ref"))
    task_ref = _mapping_value(_optional_value(task, "result_ref"))
    selected = execution_ref or task_ref
    if not selected:
        return None
    allowed_keys = {"source_service", "ref_type", "ref_id", "relation"}
    return {key: str(value) for key, value in selected.items() if key in allowed_keys}


def _safe_failure_summary(execution: Mapping[str, Any] | None) -> dict[str, Any] | None:
    failure = _mapping_value(_optional_value(execution, "failure"))
    if not failure:
        return None
    allowed_keys = {"error_code", "error_detail_sha256", "retryable"}
    return {key: deepcopy(value) for key, value in failure.items() if key in allowed_keys}


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(key)
        label = str(value) if value is not None else "NONE"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _first_text(
    task: Mapping[str, Any] | None,
    execution: Mapping[str, Any] | None,
    *,
    key: str | None = None,
    task_key: str | None = None,
    execution_key: str | None = None,
) -> str | None:
    task_value = _optional_value(task, task_key or key or "")
    execution_value = _optional_value(execution, execution_key or key or "")
    selected = task_value if task_value is not None else execution_value
    return str(selected) if selected is not None else None


def _optional_value(record: Mapping[str, Any] | None, key: str) -> Any:
    if record is None:
        return None
    return record.get(key)


def _max_timestamp(*values: Any) -> str:
    candidates = [
        _timestamp_to_wire(value)
        for value in values
        if value is not None
    ]
    if not candidates:
        return _utc_now()
    return max(candidates, key=_parse_timestamp)


def _remediation_execution_operations_redaction_summary() -> dict[str, bool]:
    return {
        "database_url_included": False,
        "service_token_included": False,
        "provider_api_key_included": False,
        "raw_prompt_included": False,
        "raw_generation_output_included": False,
        "raw_source_document_text_included": False,
        "raw_evidence_included": False,
    }


def _timestamp_to_wire(value: Any) -> str:
    if isinstance(value, datetime):
        observed = value
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        return observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _timestamp_to_wire_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return _timestamp_to_wire(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_value(value: Any) -> list[Any]:
    return deepcopy(value) if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
