from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


AG_GENERATION_QUALITY_FEEDBACK_ROLLUP_SCHEMA_VERSION = (
    "ag_generation_quality_feedback_rollup.v1"
)
MAX_ROLLUP_ITEMS = 500
DEFAULT_ROLLUP_ITEMS = 50
ATTENTION_DISPOSITION_STATUSES = {"IN_REPAIR", "ESCALATED", "ACKNOWLEDGED"}
CLOSED_DISPOSITION_STATUSES = {"RESOLVED", "DISMISSED"}
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "ERROR": 2, "CRITICAL": 3}


def build_generation_quality_feedback_rollup(
    *,
    quality_items: Iterable[Mapping[str, Any]] | None = None,
    feedback_records: Iterable[Mapping[str, Any]] | None = None,
    disposition_records: Iterable[Mapping[str, Any]] | None = None,
    request_id: str,
    trace_id: str,
    checked_at: str | None = None,
    limit: int = DEFAULT_ROLLUP_ITEMS,
) -> dict[str, Any]:
    quality_by_generation = _group_by_generation(quality_items or [])
    feedback_by_generation, unlinked_feedback_count = _group_feedback(feedback_records or [])
    disposition_by_generation = _group_by_generation(disposition_records or [])
    generation_ids = sorted(
        set(quality_by_generation) | set(feedback_by_generation) | set(disposition_by_generation)
    )
    items = [
        _rollup_item(
            generation_id,
            quality_by_generation.get(generation_id, []),
            feedback_by_generation.get(generation_id, []),
            disposition_by_generation.get(generation_id, []),
        )
        for generation_id in generation_ids
    ]
    items.sort(key=_rollup_sort_key)
    limited_items = items[:normalize_rollup_limit(limit)]
    feedback_records_list = [
        feedback for records in feedback_by_generation.values() for feedback in records
    ]
    disposition_records_list = [
        disposition
        for records in disposition_by_generation.values()
        for disposition in records
    ]
    return {
        "projection_schema_version": AG_GENERATION_QUALITY_FEEDBACK_ROLLUP_SCHEMA_VERSION,
        "checked_at": checked_at or _utc_now(),
        "trace_id": trace_id,
        "request_id": request_id,
        "items": limited_items,
        "summary": {
            "generation_count": len(generation_ids),
            "quality_item_count": sum(len(records) for records in quality_by_generation.values()),
            "feedback_count": len(feedback_records_list),
            "negative_feedback_count": sum(
                1
                for feedback in feedback_records_list
                if _safe_text(feedback.get("feedback_value")) == "negative"
            ),
            "disposition_count": len(disposition_records_list),
            "open_attention_count": sum(
                1 for item in items if item["attention_status"] in {"OPEN", "IN_PROGRESS"}
            ),
            "closed_attention_count": sum(
                1 for item in items if item["attention_status"] == "CLOSED"
            ),
            "unlinked_feedback_count": unlinked_feedback_count,
        },
        "by_feedback_value": dict(
            sorted(
                Counter(
                    _safe_text(feedback.get("feedback_value")) or "unknown"
                    for feedback in feedback_records_list
                ).items()
            )
        ),
        "by_disposition_status": dict(
            sorted(
                Counter(
                    _safe_text(disposition.get("disposition_status")) or "UNKNOWN"
                    for disposition in disposition_records_list
                ).items()
            )
        ),
        "redaction_summary": {
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_feedback_comment_included": False,
            "raw_operator_note_included": False,
        },
    }


def normalize_rollup_limit(limit: int) -> int:
    if not isinstance(limit, int):
        return DEFAULT_ROLLUP_ITEMS
    return min(max(limit, 1), MAX_ROLLUP_ITEMS)


def _rollup_item(
    generation_id: str,
    quality_records: list[Mapping[str, Any]],
    feedback_records: list[Mapping[str, Any]],
    disposition_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    latest_disposition = _latest_by_time(disposition_records, "updated_at")
    feedback_summary = _feedback_summary(feedback_records)
    quality_summary = _quality_summary(quality_records)
    disposition_summary = _disposition_summary(disposition_records, latest_disposition)
    attention_status = _attention_status(
        quality_summary=quality_summary,
        feedback_summary=feedback_summary,
        latest_disposition=latest_disposition,
    )
    severity = _item_severity(
        quality_summary=quality_summary,
        feedback_summary=feedback_summary,
        attention_status=attention_status,
    )
    return {
        "cx_generation_id": generation_id,
        "attention_status": attention_status,
        "attention_required": attention_status in {"OPEN", "IN_PROGRESS"},
        "severity": severity,
        "quality": quality_summary,
        "feedback": feedback_summary,
        "disposition": disposition_summary,
        "recommended_operator_action": _recommended_action(
            attention_status=attention_status,
            latest_disposition=latest_disposition,
            feedback_summary=feedback_summary,
            quality_summary=quality_summary,
        ),
        "debug_paths": {
            "quality_issue_detail_path": (
                f"/admin/v1/generation-audit/generations/{generation_id}"
                "/quality-issue-detail"
            ),
            "dispositions_path": (
                f"/admin/v1/generation-audit/generations/{generation_id}"
                "/quality-dispositions"
            ),
        },
    }


def _quality_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    issue_codes = sorted(
        {
            str(code)
            for record in records
            for code in _safe_list(record.get("issue_codes"))
            if isinstance(code, str) and code
        }
    )
    severities = [_safe_severity(record.get("severity")) for record in records]
    attention_required = any(record.get("attention_required") is True for record in records)
    recommended_actions = sorted(
        {
            str(action)
            for record in records
            if (action := record.get("recommended_action"))
        }
    )
    return {
        "count": len(records),
        "attention_required": attention_required,
        "max_severity": _max_severity(severities),
        "coverage_statuses": sorted(
            {
                str(status)
                for record in records
                if (status := record.get("coverage_status")) is not None
            }
        ),
        "boundary_statuses": sorted(
            {
                str(status)
                for record in records
                if (status := record.get("boundary_status")) is not None
            }
        ),
        "issue_codes": issue_codes,
        "recommended_actions": recommended_actions,
    }


def _feedback_summary(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_value = Counter(
        _safe_text(record.get("feedback_value")) or "unknown" for record in records
    )
    latest = _latest_by_time(records, "created_at")
    return {
        "count": len(records),
        "by_value": dict(sorted(by_value.items())),
        "negative_count": by_value.get("negative", 0),
        "latest_feedback_id": _safe_text(latest.get("feedback_id")) if latest else None,
        "latest_feedback_at": _safe_text(latest.get("created_at")) if latest else None,
        "quality_issue_ref_count": sum(
            len(_safe_list(record.get("quality_issue_refs"))) for record in records
        ),
    }


def _disposition_summary(
    records: list[Mapping[str, Any]],
    latest: Mapping[str, Any] | None,
) -> dict[str, Any]:
    by_status = Counter(
        _safe_text(record.get("disposition_status")) or "UNKNOWN" for record in records
    )
    return {
        "count": len(records),
        "by_status": dict(sorted(by_status.items())),
        "latest_disposition_id": (
            _safe_text(latest.get("disposition_id")) if latest else None
        ),
        "latest_status": _safe_text(latest.get("disposition_status")) if latest else None,
        "latest_action": _safe_text(latest.get("operator_action")) if latest else None,
        "latest_updated_at": _safe_text(latest.get("updated_at")) if latest else None,
        "reason_count": sum(len(_safe_list(record.get("reason_codes"))) for record in records),
    }


def _attention_status(
    *,
    quality_summary: Mapping[str, Any],
    feedback_summary: Mapping[str, Any],
    latest_disposition: Mapping[str, Any] | None,
) -> str:
    latest_status = (
        _safe_text(latest_disposition.get("disposition_status"))
        if latest_disposition
        else None
    )
    if latest_status in CLOSED_DISPOSITION_STATUSES:
        return "CLOSED"
    has_attention_signal = (
        quality_summary["attention_required"] is True
        or int(feedback_summary["negative_count"]) > 0
    )
    if latest_status in ATTENTION_DISPOSITION_STATUSES:
        return "IN_PROGRESS"
    if has_attention_signal:
        return "OPEN"
    return "OK"


def _recommended_action(
    *,
    attention_status: str,
    latest_disposition: Mapping[str, Any] | None,
    feedback_summary: Mapping[str, Any],
    quality_summary: Mapping[str, Any],
) -> str:
    if attention_status == "CLOSED":
        return "monitor_closed_disposition"
    if attention_status == "IN_PROGRESS":
        latest_status = _safe_text(latest_disposition.get("disposition_status"))
        if latest_status == "ESCALATED":
            return "follow_escalation"
        return "continue_operator_disposition"
    if int(feedback_summary["negative_count"]) > 0 and quality_summary["count"] == 0:
        return "fetch_generation_quality_detail"
    if attention_status == "OPEN":
        return "record_operator_disposition"
    return "no_action"


def _item_severity(
    *,
    quality_summary: Mapping[str, Any],
    feedback_summary: Mapping[str, Any],
    attention_status: str,
) -> str:
    if attention_status == "OK":
        return "INFO"
    if quality_summary["max_severity"] == "ERROR":
        return "ERROR"
    if int(feedback_summary["negative_count"]) > 0:
        return "WARNING"
    return str(quality_summary["max_severity"])


def _group_feedback(
    records: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, list[Mapping[str, Any]]], int]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    unlinked_count = 0
    for record in records:
        generation_id = _safe_text(record.get("cx_generation_id"))
        if generation_id is None:
            unlinked_count += 1
            continue
        grouped.setdefault(generation_id, []).append(record)
    return grouped, unlinked_count


def _group_by_generation(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        generation_id = _safe_text(record.get("cx_generation_id"))
        if generation_id is not None:
            grouped.setdefault(generation_id, []).append(record)
    return grouped


def _rollup_sort_key(item: Mapping[str, Any]) -> tuple[int, int, str, str]:
    attention_order = {"OPEN": 0, "IN_PROGRESS": 1, "CLOSED": 2, "OK": 3}
    latest_time = (
        item["disposition"].get("latest_updated_at")
        or item["feedback"].get("latest_feedback_at")
        or ""
    )
    return (
        attention_order.get(str(item["attention_status"]), 4),
        -SEVERITY_RANK.get(str(item["severity"]), 0),
        str(latest_time),
        str(item["cx_generation_id"]),
    )


def _latest_by_time(
    records: list[Mapping[str, Any]],
    field_name: str,
) -> Mapping[str, Any] | None:
    if not records:
        return None
    return max(records, key=lambda record: str(record.get(field_name) or ""))


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _safe_severity(value: Any) -> str:
    severity = str(value).upper() if isinstance(value, str) else "INFO"
    return severity if severity in SEVERITY_RANK else "INFO"


def _max_severity(severities: list[str]) -> str:
    if not severities:
        return "INFO"
    return max(severities, key=lambda severity: SEVERITY_RANK.get(severity, 0))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
