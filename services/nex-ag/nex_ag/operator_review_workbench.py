from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Header, Query, Request

from nex_runtime import request_id_from_headers, trace_id_from_headers

from .operator_reviews import (
    ALLOWED_EXPORT_STATUSES,
    ALLOWED_NOTE_STATUSES,
    ALLOWED_OPERATOR_TYPES,
    ALLOWED_TARGET_SERVICES,
    OperatorEvidenceExportStore,
    OperatorReviewNoteError,
    OperatorReviewNoteStore,
    _authorize_ag_operator_review_request,
    _operator_review_note_problem_response,
    default_operator_evidence_export_store,
    default_operator_review_note_store,
    normalize_limit,
    optional_choice,
    optional_text,
    required_text,
)


OPERATOR_REVIEW_WORKBENCH_SCHEMA_VERSION = "ag_operator_review_workbench.v1"
OPERATOR_REVIEW_WORKBENCH_ROLLUP_SCHEMA_VERSION = (
    "ag_operator_review_workbench_rollup.v1"
)


def register_operator_review_workbench_routes(
    app: FastAPI,
    *,
    note_store: Any | None = None,
    export_store: Any | None = None,
) -> None:
    selected_note_store = note_store or default_operator_review_note_store(app)
    selected_export_store = export_store or default_operator_evidence_export_store(app)

    @app.get("/admin/v1/operator-review/workbench", response_model=None)
    def get_operator_review_workbench(
        request: Request,
        authorization: str | None = Header(default=None),
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        workbench_trace_id: str | None = Query(default=None, alias="trace_id"),
        operator_type: str | None = None,
        operator_id: str | None = None,
        note_status: str | None = None,
        export_status: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_operator_review_workbench_projection_from_stores(
                note_store=selected_note_store,
                export_store=selected_export_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                item_trace_id=workbench_trace_id,
                operator_type=operator_type,
                operator_id=operator_id,
                note_status=note_status,
                export_status=export_status,
                updated_from=updated_from,
                updated_to=updated_to,
                limit=limit,
            )
        except OperatorReviewNoteError as exc:
            return _operator_review_note_problem_response(request, exc)

    @app.get("/admin/v1/operator-review/workbench/rollups", response_model=None)
    def get_operator_review_workbench_rollups(
        request: Request,
        authorization: str | None = Header(default=None),
        target_service: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        workbench_trace_id: str | None = Query(default=None, alias="trace_id"),
        operator_type: str | None = None,
        operator_id: str | None = None,
        note_status: str | None = None,
        export_status: str | None = None,
        updated_from: str | None = None,
        updated_to: str | None = None,
        limit: int | None = None,
    ):
        auth_problem = _authorize_ag_operator_review_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            projection = build_operator_review_workbench_projection_from_stores(
                note_store=selected_note_store,
                export_store=selected_export_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
                target_service=target_service,
                target_kind=target_kind,
                target_id=target_id,
                item_trace_id=workbench_trace_id,
                operator_type=operator_type,
                operator_id=operator_id,
                note_status=note_status,
                export_status=export_status,
                updated_from=updated_from,
                updated_to=updated_to,
                limit=limit,
            )
            return build_operator_review_workbench_rollup_metrics(projection)
        except OperatorReviewNoteError as exc:
            return _operator_review_note_problem_response(request, exc)


def build_operator_review_workbench_projection_from_stores(
    *,
    note_store: Any,
    export_store: Any,
    request_id: str,
    trace_id: str | None,
    target_service: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    item_trace_id: str | None = None,
    operator_type: str | None = None,
    operator_id: str | None = None,
    note_status: str | None = None,
    export_status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    filters = normalize_operator_review_workbench_filters(
        target_service=target_service,
        target_kind=target_kind,
        target_id=target_id,
        trace_id=item_trace_id,
        operator_type=operator_type,
        operator_id=operator_id,
        note_status=note_status,
        export_status=export_status,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=limit,
    )
    records_limit = filters["limit"]
    notes = note_store.list_notes(
        target_service=filters["target_service"],
        target_kind=filters["target_kind"],
        target_id=filters["target_id"],
        trace_id=filters["trace_id"],
        note_status=filters["note_status"],
        operator_type=filters["operator_type"],
        operator_id=filters["operator_id"],
        updated_from=filters["updated_from"],
        updated_to=filters["updated_to"],
        limit=records_limit,
    )
    exports = export_store.list_exports(
        target_service=filters["target_service"],
        target_kind=filters["target_kind"],
        target_id=filters["target_id"],
        trace_id=filters["trace_id"],
        export_status=filters["export_status"],
        operator_type=filters["operator_type"],
        operator_id=filters["operator_id"],
        updated_from=filters["updated_from"],
        updated_to=filters["updated_to"],
        limit=records_limit,
    )
    return build_operator_review_workbench_projection(
        notes,
        exports,
        request_id=request_id,
        trace_id=trace_id,
        filters=filters,
    )


def normalize_operator_review_workbench_filters(
    *,
    target_service: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    trace_id: str | None = None,
    operator_type: str | None = None,
    operator_id: str | None = None,
    note_status: str | None = None,
    export_status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    normalized_target_service = optional_choice(
        target_service,
        key="target_service",
        choices=ALLOWED_TARGET_SERVICES,
        default="",
    )
    normalized_operator_type = optional_choice(
        operator_type,
        key="operator_type",
        choices=ALLOWED_OPERATOR_TYPES,
        default="",
    )
    normalized_note_status = optional_choice(
        note_status,
        key="note_status",
        choices=ALLOWED_NOTE_STATUSES,
        default="",
    )
    normalized_export_status = optional_choice(
        export_status,
        key="export_status",
        choices=ALLOWED_EXPORT_STATUSES,
        default="",
    )
    return {
        "target_service": normalized_target_service or None,
        "target_kind": optional_text(target_kind),
        "target_id": optional_text(target_id),
        "trace_id": optional_text(trace_id),
        "operator_type": normalized_operator_type or None,
        "operator_id": optional_text(operator_id),
        "note_status": normalized_note_status or None,
        "export_status": normalized_export_status or None,
        "updated_from": normalize_operator_review_workbench_timestamp(
            updated_from,
            key="updated_from",
        ),
        "updated_to": normalize_operator_review_workbench_timestamp(
            updated_to,
            key="updated_to",
        ),
        "limit": normalize_limit(limit),
    }


def normalize_operator_review_workbench_timestamp(
    value: Any,
    *,
    key: str,
) -> str | None:
    normalized = optional_text(value)
    if normalized is None:
        return None
    parse_candidate = (
        f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
    )
    try:
        parsed = datetime.fromisoformat(parse_candidate)
    except ValueError as exc:
        raise OperatorReviewNoteError(
            status_code=422,
            error_code=f"ag.operator_review_note_{key}_invalid",
            detail=f"{key} must be an ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_operator_review_workbench_projection(
    notes: list[dict[str, Any]],
    exports: list[dict[str, Any]],
    *,
    request_id: str,
    trace_id: str | None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for note in notes:
        key = _target_key(note)
        grouped.setdefault(key, _empty_workbench_item(note))["notes"].append(
            _safe_note_ref(note)
        )
    for export in exports:
        key = _target_key(export)
        grouped.setdefault(key, _empty_workbench_item(export))["evidence_exports"].append(
            _safe_export_ref(export)
        )

    items = [_finalize_workbench_item(item) for item in grouped.values()]
    items.sort(
        key=lambda item: (
            str(item["latest_updated_at"] or ""),
            item["target_ref"]["target_service"],
            item["target_ref"]["target_kind"],
            item["target_ref"]["target_id"],
        ),
        reverse=True,
    )
    summary = _workbench_summary(items)
    return {
        "workbench_schema_version": OPERATOR_REVIEW_WORKBENCH_SCHEMA_VERSION,
        "trace_id": optional_text(trace_id),
        "request_id": required_text({"request_id": request_id}, "request_id"),
        "filters": filters or normalize_operator_review_workbench_filters(),
        "items": items,
        "summary": summary,
        "redaction": {
            "raw_operator_note_included": False,
            "raw_evidence_body_included": False,
            "raw_prompt_included": False,
            "raw_source_text_included": False,
            "storage_paths_included": False,
            "idempotency_keys_included": False,
            "note_body_shape": "hash_and_short_preview_only",
            "evidence_shape": "redacted_manifest_plus_hashes",
        },
    }


def build_operator_review_workbench_rollup_metrics(
    projection: dict[str, Any],
) -> dict[str, Any]:
    items = list(projection.get("items") or [])
    notes = [note for item in items for note in item.get("notes", [])]
    exports = [
        export for item in items for export in item.get("evidence_exports", [])
    ]
    attention_items = [_attention_item(item) for item in items]
    attention_items = [
        item for item in attention_items if item["attention_status"] != "OK"
    ]
    attention_items.sort(
        key=lambda item: (
            _attention_sort_rank(item["attention_status"]),
            str(item["latest_updated_at"] or ""),
            item["target_ref"]["target_service"],
            item["target_ref"]["target_kind"],
            item["target_ref"]["target_id"],
        )
    )
    return {
        "rollup_schema_version": OPERATOR_REVIEW_WORKBENCH_ROLLUP_SCHEMA_VERSION,
        "trace_id": projection.get("trace_id"),
        "request_id": projection.get("request_id"),
        "filters": dict(projection.get("filters") or {}),
        "summary": {
            "target_count": len(items),
            "note_count": len(notes),
            "export_count": len(exports),
            "open_note_count": _count_matching(notes, "note_status", "ACTIVE"),
            "resolved_note_count": _count_matching(notes, "note_status", "RESOLVED"),
            "deleted_note_count": _count_matching(notes, "note_status", "DELETED"),
            "high_urgency_note_count": sum(
                1
                for note in notes
                if note.get("severity") in {"HIGH", "URGENT"}
                and note.get("note_status") == "ACTIVE"
            ),
            "ready_export_count": _count_matching(exports, "export_status", "READY"),
            "failed_export_count": _count_matching(exports, "export_status", "FAILED"),
            "evidence_item_count": sum(
                int(export.get("evidence_item_count") or 0) for export in exports
            ),
            "attention_target_count": len(attention_items),
        },
        "by_target_service": _count_items_by_target(items, "target_service"),
        "by_target_kind": _count_items_by_target(items, "target_kind"),
        "by_note_status": _count_by(notes, "note_status"),
        "by_note_severity": _count_by(notes, "severity"),
        "by_export_status": _count_by(exports, "export_status"),
        "by_export_format": _count_by(exports, "export_format"),
        "attention": {
            "items": attention_items,
            "by_status": _count_by(attention_items, "attention_status"),
        },
        "redaction": dict(projection.get("redaction") or {}),
    }


def _target_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("target_service") or ""),
        str(record.get("target_kind") or ""),
        str(record.get("target_id") or ""),
    )


def _empty_workbench_item(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": str(record.get("target_service") or ""),
            "target_kind": str(record.get("target_kind") or ""),
            "target_id": str(record.get("target_id") or ""),
        },
        "notes": [],
        "evidence_exports": [],
    }


def _safe_note_ref(record: dict[str, Any]) -> dict[str, Any]:
    operator = _operator_ref(record)
    return {
        "operator_note_id": record.get("operator_note_id"),
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "note_status": record.get("note_status"),
        "note_type": record.get("note_type"),
        "severity": record.get("severity"),
        "operator_ref": operator,
        "operator_note_hash": record.get("operator_note_hash"),
        "operator_note_preview": record.get("operator_note_preview"),
        "reason_codes": list(record.get("reason_codes") or []),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _safe_export_ref(record: dict[str, Any]) -> dict[str, Any]:
    operator = _operator_ref(record)
    return {
        "export_id": record.get("export_id"),
        "trace_id": record.get("trace_id"),
        "request_id": record.get("request_id"),
        "export_status": record.get("export_status"),
        "export_format": record.get("export_format"),
        "redaction_profile": record.get("redaction_profile"),
        "evidence_hash": record.get("evidence_hash"),
        "evidence_item_count": int(record.get("evidence_item_count") or 0),
        "operator_ref": operator,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _operator_ref(record: dict[str, Any]) -> dict[str, str | None]:
    operator = record.get("operator_ref")
    if not isinstance(operator, dict):
        return {"operator_type": None, "operator_id": None, "tenant_id": None}
    return {
        "operator_type": optional_text(operator.get("operator_type")),
        "operator_id": optional_text(operator.get("operator_id")),
        "tenant_id": optional_text(operator.get("tenant_id")),
    }


def _finalize_workbench_item(item: dict[str, Any]) -> dict[str, Any]:
    notes = sorted(
        item["notes"],
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("operator_note_id") or ""),
        ),
        reverse=True,
    )
    exports = sorted(
        item["evidence_exports"],
        key=lambda record: (
            str(record.get("updated_at") or ""),
            str(record.get("export_id") or ""),
        ),
        reverse=True,
    )
    latest_updated_at = _latest_updated_at(notes + exports)
    trace_ids = sorted(
        {
            str(record["trace_id"])
            for record in notes + exports
            if record.get("trace_id") is not None
        }
    )
    return {
        "target_ref": item["target_ref"],
        "latest_updated_at": latest_updated_at,
        "trace_ids": trace_ids,
        "notes": notes,
        "evidence_exports": exports,
        "note_summary": _note_summary(notes),
        "export_summary": _export_summary(exports),
        "raw_payloads_included": False,
    }


def _note_summary(notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(notes),
        "by_status": _count_by(notes, "note_status"),
        "by_severity": _count_by(notes, "severity"),
        "latest_updated_at": _latest_updated_at(notes),
    }


def _export_summary(exports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(exports),
        "by_status": _count_by(exports, "export_status"),
        "by_format": _count_by(exports, "export_format"),
        "evidence_item_count": sum(
            int(record.get("evidence_item_count") or 0) for record in exports
        ),
        "latest_updated_at": _latest_updated_at(exports),
    }


def _workbench_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    notes = [note for item in items for note in item["notes"]]
    exports = [export for item in items for export in item["evidence_exports"]]
    latest_values = [
        str(item["latest_updated_at"]) for item in items if item.get("latest_updated_at")
    ]
    return {
        "target_count": len(items),
        "note_count": len(notes),
        "export_count": len(exports),
        "open_note_count": sum(
            1 for note in notes if note.get("note_status") == "ACTIVE"
        ),
        "failed_export_count": sum(
            1 for export in exports if export.get("export_status") == "FAILED"
        ),
        "latest_updated_at": max(latest_values) if latest_values else None,
    }


def _attention_item(item: dict[str, Any]) -> dict[str, Any]:
    notes = list(item.get("notes") or [])
    exports = list(item.get("evidence_exports") or [])
    reasons: list[str] = []
    if any(export.get("export_status") == "FAILED" for export in exports):
        reasons.append("failed_evidence_export")
    if any(
        note.get("note_status") == "ACTIVE"
        and note.get("severity") in {"HIGH", "URGENT"}
        for note in notes
    ):
        reasons.append("active_high_urgency_note")
    if any(note.get("note_status") == "ACTIVE" for note in notes):
        reasons.append("active_operator_note")

    if "failed_evidence_export" in reasons:
        status = "BLOCKED"
    elif "active_high_urgency_note" in reasons:
        status = "ATTENTION"
    elif "active_operator_note" in reasons:
        status = "OPEN"
    else:
        status = "OK"
    return {
        "target_ref": dict(item["target_ref"]),
        "attention_status": status,
        "reason_codes": reasons,
        "note_count": len(notes),
        "export_count": len(exports),
        "latest_updated_at": item.get("latest_updated_at"),
    }


def _attention_sort_rank(status: str) -> int:
    return {"BLOCKED": 0, "ATTENTION": 1, "OPEN": 2}.get(status, 3)


def _count_matching(records: list[dict[str, Any]], key: str, value: str) -> int:
    return sum(1 for record in records if record.get(key) == value)


def _count_items_by_target(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        target = item.get("target_ref") if isinstance(item.get("target_ref"), dict) else {}
        value = str(target.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = str(record.get(key) or "UNKNOWN")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _latest_updated_at(records: list[dict[str, Any]]) -> str | None:
    values = [str(record["updated_at"]) for record in records if record.get("updated_at")]
    return max(values) if values else None
