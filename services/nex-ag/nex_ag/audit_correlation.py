from __future__ import annotations

import re
from typing import Any, Mapping

from nex_ag.audit_integrity import (
    MAX_AUDIT_INTEGRITY_EVENTS,
    AuditIntegrityError,
    build_audit_event_integrity_report,
    sha256_canonical_json,
)


AUDIT_CORRELATION_REPORT_SCHEMA_VERSION = "ag_audit_correlation_report.v1"
AUDIT_CORRELATION_TRACE_SCHEMA_VERSION = "ag_audit_correlation_trace.v1"
MAX_AUDIT_CORRELATION_EXPORTS = 500
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def build_audit_correlation_continuity_report(
    events: list[dict[str, Any]],
    *,
    evidence_exports: list[dict[str, Any]] | None = None,
    expected_trace_ids: list[str] | None = None,
    required_event_types: list[str] | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    exports = _export_list(evidence_exports)
    normalized_expected_traces = _text_list(
        expected_trace_ids,
        field="expected_trace_ids",
    )
    normalized_required_types = _text_list(
        required_event_types,
        field="required_event_types",
    )
    integrity = build_audit_event_integrity_report(
        events,
        checked_at=checked_at,
    )
    valid_ids = {str(item["event_id"]) for item in integrity["items"]}
    valid_events = _valid_event_map(events, valid_ids)
    traces: dict[str, dict[str, Any]] = {}
    request_traces: dict[str, set[str]] = {}
    issues: list[dict[str, Any]] = []

    if integrity["integrity_status"] == "FAILED":
        issues.append(
            {
                "issue_code": "event_integrity_failed",
                "subject_id": None,
                "trace_ids": [],
                "missing_event_types": [],
            }
        )
    for event_id, event in valid_events.items():
        trace_id = _optional_text(event.get("trace_id"))
        if trace_id is None:
            issues.append(
                {
                    "issue_code": "event_trace_id_missing",
                    "subject_id": event_id,
                    "trace_ids": [],
                    "missing_event_types": [],
                }
            )
            continue
        trace = traces.setdefault(
            trace_id,
            {
                "trace_id": trace_id,
                "event_ids": [],
                "event_types": [],
                "request_ids": [],
                "subject_refs": [],
                "evidence_export_ids": [],
            },
        )
        trace["event_ids"].append(event_id)
        _append_unique(trace["event_types"], str(event["event_type"]))
        request_id = _optional_text(event.get("request_id"))
        if request_id is not None:
            _append_unique(trace["request_ids"], request_id)
            request_traces.setdefault(request_id, set()).add(trace_id)
        subject_ref = event.get("subject_ref")
        if isinstance(subject_ref, Mapping):
            normalized_subject = {
                "type": str(subject_ref.get("type") or ""),
                "id": str(subject_ref.get("id") or ""),
            }
            if normalized_subject not in trace["subject_refs"]:
                trace["subject_refs"].append(normalized_subject)

    for request_id, trace_ids in request_traces.items():
        if len(trace_ids) > 1:
            issues.append(
                {
                    "issue_code": "request_trace_conflict",
                    "subject_id": request_id,
                    "trace_ids": sorted(trace_ids),
                    "missing_event_types": [],
                }
            )

    export_items, export_issues = _link_exports(exports, traces)
    issues.extend(export_issues)
    for trace_id in normalized_expected_traces:
        if trace_id not in traces:
            issues.append(
                {
                    "issue_code": "expected_trace_missing",
                    "subject_id": trace_id,
                    "trace_ids": [trace_id],
                    "missing_event_types": [],
                }
            )
    for trace_id, trace in traces.items():
        missing_types = sorted(
            set(normalized_required_types) - set(trace["event_types"])
        )
        if missing_types:
            issues.append(
                {
                    "issue_code": "required_event_type_missing",
                    "subject_id": trace_id,
                    "trace_ids": [trace_id],
                    "missing_event_types": missing_types,
                }
            )

    trace_items = [_trace_projection(traces[key]) for key in sorted(traces)]
    issues.sort(
        key=lambda issue: (
            str(issue.get("subject_id") or ""),
            str(issue.get("issue_code") or ""),
        )
    )
    status = "CONTIGUOUS" if not issues else "FAILED"
    if not events and not exports and not normalized_expected_traces:
        status = "NO_CORRELATION"
    verification_payload = {
        "event_integrity_report_hash": integrity["report_hash"],
        "traces": trace_items,
        "evidence_exports": export_items,
        "issues": issues,
        "expected_trace_ids": normalized_expected_traces,
        "required_event_types": normalized_required_types,
    }
    return {
        "correlation_report_schema_version": (
            AUDIT_CORRELATION_REPORT_SCHEMA_VERSION
        ),
        "continuity_status": status,
        "checked_at": integrity["checked_at"],
        "report_hash": sha256_canonical_json(verification_payload),
        "event_integrity": {
            "integrity_status": integrity["integrity_status"],
            "report_hash": integrity["report_hash"],
            "summary": integrity["summary"],
        },
        "summary": {
            "trace_count": len(trace_items),
            "event_count": sum(item["event_count"] for item in trace_items),
            "evidence_export_count": len(export_items),
            "linked_evidence_export_count": sum(
                1 for item in export_items if item["linked"]
            ),
            "orphan_evidence_export_count": sum(
                1 for item in export_items if not item["linked"]
            ),
            "request_trace_conflict_count": sum(
                1
                for issue in issues
                if issue["issue_code"] == "request_trace_conflict"
            ),
            "issue_count": len(issues),
        },
        "expectations": {
            "trace_ids": normalized_expected_traces,
            "required_event_types": normalized_required_types,
        },
        "traces": trace_items,
        "evidence_exports": export_items,
        "issues": issues,
        "redaction": {
            "event_messages_included": False,
            "event_details_included": False,
            "evidence_bodies_included": False,
            "credentials_included": False,
            "storage_paths_included": False,
        },
    }


def _export_list(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AuditIntegrityError(
            error_code="ag.audit_correlation.evidence_exports_invalid",
            detail="evidence_exports must be a list when supplied.",
        )
    if len(value) > MAX_AUDIT_CORRELATION_EXPORTS:
        raise AuditIntegrityError(
            error_code="ag.audit_correlation.evidence_exports_limit_exceeded",
            detail=(
                f"evidence_exports cannot exceed {MAX_AUDIT_CORRELATION_EXPORTS} "
                "items."
            ),
        )
    return value


def _valid_event_map(
    events: list[dict[str, Any]],
    valid_ids: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = _optional_text(event.get("event_id"))
        if event_id in valid_ids and event_id not in result:
            result[str(event_id)] = event
    return result


def _link_exports(
    exports: list[dict[str, Any]],
    traces: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for export in exports:
        if not isinstance(export, dict):
            issues.append(_export_issue("evidence_export_invalid", None, []))
            continue
        export_id = _optional_text(export.get("export_id"))
        trace_id = _optional_text(export.get("trace_id"))
        evidence_hash = _optional_text(export.get("evidence_hash"))
        if export_id is None:
            issues.append(_export_issue("evidence_export_id_missing", None, []))
            continue
        if export_id in seen:
            issues.append(_export_issue("duplicate_evidence_export_id", export_id, []))
            continue
        seen.add(export_id)
        if trace_id is None:
            issues.append(_export_issue("evidence_export_trace_id_missing", export_id, []))
        hash_valid = (
            evidence_hash is not None
            and _SHA256_PATTERN.fullmatch(evidence_hash.lower()) is not None
        )
        if not hash_valid:
            issues.append(_export_issue("evidence_export_hash_invalid", export_id, []))
        linked = trace_id in traces if trace_id is not None else False
        if trace_id is not None and not linked:
            issues.append(
                _export_issue("evidence_export_trace_orphaned", export_id, [trace_id])
            )
        if linked:
            traces[str(trace_id)]["evidence_export_ids"].append(export_id)
        items.append(
            {
                "export_id": export_id,
                "trace_id": trace_id,
                "evidence_hash": evidence_hash.lower() if hash_valid else None,
                "linked": linked,
            }
        )
    items.sort(key=lambda item: item["export_id"])
    return items, issues


def _export_issue(
    issue_code: str,
    subject_id: str | None,
    trace_ids: list[str],
) -> dict[str, Any]:
    return {
        "issue_code": issue_code,
        "subject_id": subject_id,
        "trace_ids": trace_ids,
        "missing_event_types": [],
    }


def _trace_projection(value: dict[str, Any]) -> dict[str, Any]:
    event_ids = sorted(value["event_ids"])
    event_types = sorted(value["event_types"])
    request_ids = sorted(value["request_ids"])
    subject_refs = sorted(
        value["subject_refs"],
        key=lambda item: (item["type"], item["id"]),
    )
    export_ids = sorted(value["evidence_export_ids"])
    return {
        "correlation_trace_schema_version": AUDIT_CORRELATION_TRACE_SCHEMA_VERSION,
        "trace_id": value["trace_id"],
        "event_ids": event_ids,
        "event_types": event_types,
        "request_ids": request_ids,
        "subject_refs": subject_refs,
        "evidence_export_ids": export_ids,
        "event_count": len(event_ids),
        "request_count": len(request_ids),
        "subject_count": len(subject_refs),
        "evidence_export_count": len(export_ids),
    }


def _text_list(value: list[str] | None, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AuditIntegrityError(
            error_code=f"ag.audit_correlation.{field}_invalid",
            detail=f"{field} must be a list when supplied.",
        )
    result: list[str] = []
    for item in value:
        normalized = _optional_text(item)
        if normalized is None:
            raise AuditIntegrityError(
                error_code=f"ag.audit_correlation.{field}_item_invalid",
                detail=f"{field} items must be non-empty strings.",
            )
        _append_unique(result, normalized)
    return sorted(result)


def _append_unique(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "AUDIT_CORRELATION_REPORT_SCHEMA_VERSION",
    "AUDIT_CORRELATION_TRACE_SCHEMA_VERSION",
    "MAX_AUDIT_CORRELATION_EXPORTS",
    "MAX_AUDIT_INTEGRITY_EVENTS",
    "build_audit_correlation_continuity_report",
]
