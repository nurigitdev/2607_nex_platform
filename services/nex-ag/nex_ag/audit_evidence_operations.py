from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Mapping

from nex_runtime import OperationalEventStore


AUDIT_EVIDENCE_OPERATIONS_SCHEMA_VERSION = (
    "ag_audit_evidence_operations_projection.v1"
)
AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE = (
    "ag.audit_evidence_package.generated"
)
AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE = (
    "ag.audit_evidence_package.verified"
)
AUDIT_EVIDENCE_OPERATIONS_PATH = "/admin/v1/operations/audit-integrity"
AUDIT_EVIDENCE_PACKAGE_CREATE_PATH = (
    "/admin/v1/audit-integrity/evidence-packages"
)
AUDIT_EVIDENCE_PACKAGE_VERIFY_PATH = (
    "/admin/v1/audit-integrity/evidence-packages/verify"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_ID_PATTERN = re.compile(r"^ag-audit-package-[0-9a-f]{32}$")


def build_audit_evidence_operations_projection(
    *,
    event_store: OperationalEventStore,
    export_store: Any | None,
    service_id: str | None = None,
    recent_limit: int = 5,
    request_trace_id: str | None = None,
) -> dict[str, Any]:
    bounded_limit = max(1, min(50, int(recent_limit)))
    if service_id not in {None, "nex-ag"}:
        return _base_projection(
            projection_status="READY",
            integrity_status="FILTERED",
            event_records=[],
            export_records=[],
            event_source_status=_source_status("FILTERED", "service_operational_events"),
            export_source_status=_source_status("FILTERED", "ag_ev_exports"),
            recent_limit=bounded_limit,
            request_trace_id=request_trace_id,
        )

    event_records: list[dict[str, Any]] | None
    export_records: list[dict[str, Any]] | None
    try:
        event_records = _audit_events(event_store)
        event_status = _source_status(
            "READY",
            "service_operational_events",
            record_count=len(event_records),
        )
    except Exception:
        event_records = None
        event_status = _source_status(
            "UNAVAILABLE",
            "service_operational_events",
            error_code="ag.audit_evidence.event_source_unavailable",
        )
    if export_store is None:
        export_records = []
        export_status = _source_status("NOT_CONFIGURED", "ag_ev_exports")
    else:
        try:
            export_records = export_store.list_exports(limit=500)
            export_status = _source_status(
                "READY",
                "ag_ev_exports",
                record_count=len(export_records),
            )
        except Exception:
            export_records = None
            export_status = _source_status(
                "UNAVAILABLE",
                "ag_ev_exports",
                error_code="ag.audit_evidence.export_source_unavailable",
            )

    if event_records is None or export_records is None:
        projection_status = "DEGRADED"
        integrity_status = "SOURCE_UNAVAILABLE"
    elif export_store is None:
        projection_status = "NOT_CONFIGURED"
        integrity_status = "EMPTY" if not event_records else "READY"
    else:
        projection_status = "READY"
        integrity_status = _integrity_status(event_records, export_records)
    return _base_projection(
        projection_status=projection_status,
        integrity_status=integrity_status,
        event_records=event_records or [],
        export_records=export_records or [],
        event_source_status=event_status,
        export_source_status=export_status,
        recent_limit=bounded_limit,
        request_trace_id=request_trace_id,
    )


def _audit_events(event_store: OperationalEventStore) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for event_type in (
        AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
        AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
    ):
        for event in event_store.list_events(event_type=event_type, limit=500):
            events[str(event["event_id"])] = event
    return sorted(
        events.values(),
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("event_id") or ""),
        ),
        reverse=True,
    )


def _integrity_status(
    events: list[dict[str, Any]],
    exports: list[dict[str, Any]],
) -> str:
    invalid_hashes = any(_safe_hash(item.get("evidence_hash")) is None for item in exports)
    failed_actions = any(
        _event_status(event) == "FAILED"
        for event in events
    )
    if invalid_hashes or failed_actions:
        return "ATTENTION"
    if not events and not exports:
        return "EMPTY"
    return "READY"


def _base_projection(
    *,
    projection_status: str,
    integrity_status: str,
    event_records: list[dict[str, Any]],
    export_records: list[dict[str, Any]],
    event_source_status: dict[str, Any],
    export_source_status: dict[str, Any],
    recent_limit: int,
    request_trace_id: str | None,
) -> dict[str, Any]:
    generated = [
        event
        for event in event_records
        if event.get("event_type") == AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE
    ]
    verified = [
        event
        for event in event_records
        if event.get("event_type") == AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE
    ]
    valid_hash_count = sum(
        1 for item in export_records if _safe_hash(item.get("evidence_hash")) is not None
    )
    projection = {
        "projection_schema_version": AUDIT_EVIDENCE_OPERATIONS_SCHEMA_VERSION,
        "projection_status": projection_status,
        "integrity_status": integrity_status,
        "checked_at": _utc_now(),
        "summary": {
            "package_generation_count": len(generated),
            "package_verification_count": len(verified),
            "failed_action_count": sum(
                1 for event in event_records if _event_status(event) == "FAILED"
            ),
            "evidence_export_count": len(export_records),
            "hash_ready_export_count": valid_hash_count,
            "invalid_hash_export_count": len(export_records) - valid_hash_count,
        },
        "recent_actions": [
            _event_projection(event) for event in event_records[:recent_limit]
        ],
        "recent_exports": [
            _export_projection(item)
            for item in sorted(
                export_records,
                key=lambda record: (
                    str(record.get("updated_at") or ""),
                    str(record.get("export_id") or ""),
                ),
                reverse=True,
            )[:recent_limit]
        ],
        "source_statuses": {
            "operational_events": event_source_status,
            "evidence_exports": export_source_status,
        },
        "paths": {
            "operations": AUDIT_EVIDENCE_OPERATIONS_PATH,
            "create_package": AUDIT_EVIDENCE_PACKAGE_CREATE_PATH,
            "verify_package": AUDIT_EVIDENCE_PACKAGE_VERIFY_PATH,
        },
        "new_tables_required": False,
        "redaction": {
            "event_messages_included": False,
            "event_details_included": False,
            "evidence_manifests_included": False,
            "operator_refs_included": False,
            "credentials_included": False,
            "storage_paths_included": False,
        },
    }
    if request_trace_id is not None:
        projection["request_trace_id"] = request_trace_id
    return projection


def _event_projection(event: Mapping[str, Any]) -> dict[str, Any]:
    details = event.get("details")
    safe_details = details if isinstance(details, Mapping) else {}
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "severity": event.get("severity"),
        "trace_id": event.get("trace_id"),
        "request_id": event.get("request_id"),
        "package_id": _safe_package_id(safe_details.get("package_id")),
        "package_hash": _safe_hash(safe_details.get("package_hash")),
        "verification_status": _event_status(event),
        "issue_count": _safe_non_negative_int(safe_details.get("issue_count")),
        "created_at": event.get("created_at"),
    }


def _export_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "export_id": item.get("export_id"),
        "trace_id": item.get("trace_id"),
        "export_status": item.get("export_status"),
        "evidence_hash": _safe_hash(item.get("evidence_hash")),
        "evidence_item_count": _safe_non_negative_int(
            item.get("evidence_item_count")
        ),
        "redaction_profile": item.get("redaction_profile"),
        "updated_at": item.get("updated_at"),
    }


def _event_status(event: Mapping[str, Any]) -> str | None:
    details = event.get("details")
    if not isinstance(details, Mapping):
        return None
    status = details.get("verification_status")
    return str(status) if status in {"VERIFIED", "FAILED", "NO_EVIDENCE"} else None


def _safe_hash(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    return normalized if _SHA256_PATTERN.fullmatch(normalized) else None


def _safe_package_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if _PACKAGE_ID_PATTERN.fullmatch(value) else None


def _safe_non_negative_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _source_status(
    status: str,
    table: str,
    *,
    record_count: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "service_id": "nex-ag",
        "source_table": table,
        "read_only": True,
    }
    if record_count is not None:
        result["record_count"] = record_count
    if error_code is not None:
        result["error_code"] = error_code
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "AUDIT_EVIDENCE_OPERATIONS_PATH",
    "AUDIT_EVIDENCE_OPERATIONS_SCHEMA_VERSION",
    "AUDIT_EVIDENCE_PACKAGE_CREATE_PATH",
    "AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE",
    "AUDIT_EVIDENCE_PACKAGE_VERIFY_PATH",
    "AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE",
    "build_audit_evidence_operations_projection",
]
