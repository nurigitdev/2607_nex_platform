from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ag.audit_correlation import (
    AUDIT_CORRELATION_REPORT_SCHEMA_VERSION,
    AUDIT_CORRELATION_TRACE_SCHEMA_VERSION,
    MAX_AUDIT_CORRELATION_EXPORTS,
    build_audit_correlation_continuity_report,
)
from nex_ag.audit_integrity import AuditIntegrityError
from nex_runtime.operational_events import build_operational_event


CHECKED_AT = "2026-09-20T03:00:00Z"


def _event(
    event_id: str,
    *,
    trace_id: str | None = "trace-0863",
    request_id: str | None = "request-0863",
    event_type: str = "ag.audit.started",
    created_at: str = "2026-09-20T02:00:00Z",
    subject_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    return build_operational_event(
        service_id="nex-ag",
        event_type=event_type,
        severity="INFO",
        message="Correlation body must stay private.",
        trace_id=trace_id,
        request_id=request_id,
        subject_ref=subject_ref
        if subject_ref is not None
        else {"type": "audit_case", "id": "case-0863"},
        details={"authorization": "secret", "safe_count": 1},
        created_at=created_at,
        event_id=event_id,
    )


def _export(
    export_id: str,
    *,
    trace_id: str | None = "trace-0863",
    evidence_hash: str | None = None,
) -> dict[str, object]:
    return {
        "export_id": export_id,
        "trace_id": trace_id,
        "evidence_hash": evidence_hash if evidence_hash is not None else "a" * 64,
        "body": "must-not-appear",
        "storage_path": "/private/evidence.json",
    }


def test_continuity_report_links_sorted_trace_metadata_and_redacts() -> None:
    completed = _event(
        "event-completed",
        event_type="ag.audit.completed",
        created_at="2026-09-20T02:01:00Z",
    )
    started = _event("event-started")
    events = [completed, started]
    original = deepcopy(events)

    result = build_audit_correlation_continuity_report(
        events,
        evidence_exports=[_export("export-0863", evidence_hash="B" * 64)],
        expected_trace_ids=["trace-0863", "trace-0863"],
        required_event_types=[
            "ag.audit.completed",
            "ag.audit.started",
            "ag.audit.completed",
        ],
        checked_at=CHECKED_AT,
    )
    repeated = build_audit_correlation_continuity_report(
        list(reversed(events)),
        evidence_exports=[_export("export-0863", evidence_hash="b" * 64)],
        expected_trace_ids=["trace-0863"],
        required_event_types=["ag.audit.started", "ag.audit.completed"],
        checked_at="2026-09-20T04:00:00Z",
    )

    assert result["correlation_report_schema_version"] == (
        AUDIT_CORRELATION_REPORT_SCHEMA_VERSION
    )
    assert result["continuity_status"] == "CONTIGUOUS"
    assert result["summary"] == {
        "trace_count": 1,
        "event_count": 2,
        "evidence_export_count": 1,
        "linked_evidence_export_count": 1,
        "orphan_evidence_export_count": 0,
        "request_trace_conflict_count": 0,
        "issue_count": 0,
    }
    trace = result["traces"][0]
    assert trace == {
        "correlation_trace_schema_version": (
            AUDIT_CORRELATION_TRACE_SCHEMA_VERSION
        ),
        "trace_id": "trace-0863",
        "event_ids": ["event-completed", "event-started"],
        "event_types": ["ag.audit.completed", "ag.audit.started"],
        "request_ids": ["request-0863"],
        "subject_refs": [{"type": "audit_case", "id": "case-0863"}],
        "evidence_export_ids": ["export-0863"],
        "event_count": 2,
        "request_count": 1,
        "subject_count": 1,
        "evidence_export_count": 1,
    }
    assert result["evidence_exports"] == [
        {
            "export_id": "export-0863",
            "trace_id": "trace-0863",
            "evidence_hash": "b" * 64,
            "linked": True,
        }
    ]
    assert result["report_hash"] == repeated["report_hash"]
    assert events == original
    serialized = str(result)
    assert "Correlation body must stay private" not in serialized
    assert "authorization" not in serialized
    assert "must-not-appear" not in serialized
    assert "/private/evidence.json" not in serialized


def test_empty_report_has_explicit_no_correlation_status() -> None:
    result = build_audit_correlation_continuity_report([], checked_at=CHECKED_AT)

    assert result["continuity_status"] == "NO_CORRELATION"
    assert result["event_integrity"]["integrity_status"] == "NO_EVENTS"
    assert result["summary"]["issue_count"] == 0


def test_missing_event_trace_and_invalid_event_integrity_are_reported() -> None:
    no_trace = _event("event-no-trace", trace_id=None)
    invalid = _event("event-invalid")
    invalid.pop("severity")

    result = build_audit_correlation_continuity_report(
        [no_trace, invalid, "not-an-event"],  # type: ignore[list-item]
        checked_at=CHECKED_AT,
    )

    assert result["continuity_status"] == "FAILED"
    assert result["summary"]["trace_count"] == 0
    assert {issue["issue_code"] for issue in result["issues"]} == {
        "event_integrity_failed",
        "event_trace_id_missing",
    }


def test_request_id_cannot_span_multiple_traces() -> None:
    without_subject = _event(
        "event-c",
        trace_id="trace-b",
        request_id=None,
    )
    without_subject["subject_ref"] = None
    result = build_audit_correlation_continuity_report(
        [
            _event("event-a", trace_id="trace-a", request_id="shared-request"),
            _event("event-b", trace_id="trace-b", request_id="shared-request"),
            without_subject,
        ],
        checked_at=CHECKED_AT,
    )

    assert result["continuity_status"] == "FAILED"
    assert result["summary"]["request_trace_conflict_count"] == 1
    conflict = result["issues"][0]
    assert conflict["issue_code"] == "request_trace_conflict"
    assert conflict["subject_id"] == "shared-request"
    assert conflict["trace_ids"] == ["trace-a", "trace-b"]


def test_expected_trace_and_required_event_types_are_enforced() -> None:
    result = build_audit_correlation_continuity_report(
        [_event("event-present", trace_id="trace-present")],
        expected_trace_ids=["trace-missing", "trace-present"],
        required_event_types=["ag.audit.completed", "ag.audit.started"],
        checked_at=CHECKED_AT,
    )

    assert result["continuity_status"] == "FAILED"
    assert result["expectations"] == {
        "trace_ids": ["trace-missing", "trace-present"],
        "required_event_types": ["ag.audit.completed", "ag.audit.started"],
    }
    assert {issue["issue_code"] for issue in result["issues"]} == {
        "expected_trace_missing",
        "required_event_type_missing",
    }
    missing_type = next(
        issue
        for issue in result["issues"]
        if issue["issue_code"] == "required_event_type_missing"
    )
    assert missing_type["missing_event_types"] == ["ag.audit.completed"]


def test_evidence_export_shape_hash_duplicates_and_orphans_are_reported() -> None:
    exports: list[object] = [
        "invalid",
        {"trace_id": "trace-0863", "evidence_hash": "a" * 64},
        _export("export-duplicate"),
        _export("export-duplicate"),
        _export("export-no-trace", trace_id=None),
        _export("export-bad-hash", evidence_hash="bad"),
        _export("export-orphan", trace_id="trace-orphan"),
    ]

    result = build_audit_correlation_continuity_report(
        [_event("event-valid")],
        evidence_exports=exports,  # type: ignore[arg-type]
        checked_at=CHECKED_AT,
    )

    assert result["continuity_status"] == "FAILED"
    assert result["summary"]["evidence_export_count"] == 4
    assert result["summary"]["linked_evidence_export_count"] == 2
    assert result["summary"]["orphan_evidence_export_count"] == 2
    assert {issue["issue_code"] for issue in result["issues"]} == {
        "duplicate_evidence_export_id",
        "evidence_export_hash_invalid",
        "evidence_export_id_missing",
        "evidence_export_invalid",
        "evidence_export_trace_id_missing",
        "evidence_export_trace_orphaned",
    }
    bad_hash = next(
        item
        for item in result["evidence_exports"]
        if item["export_id"] == "export-bad-hash"
    )
    assert bad_hash["evidence_hash"] is None


@pytest.mark.parametrize(
    ("value", "error_code"),
    [
        ("bad", "ag.audit_correlation.evidence_exports_invalid"),
        (
            [{} for _ in range(MAX_AUDIT_CORRELATION_EXPORTS + 1)],
            "ag.audit_correlation.evidence_exports_limit_exceeded",
        ),
    ],
)
def test_evidence_export_collection_is_bounded(
    value: object,
    error_code: str,
) -> None:
    with pytest.raises(AuditIntegrityError) as exc_info:
        build_audit_correlation_continuity_report(
            [],
            evidence_exports=value,  # type: ignore[arg-type]
            checked_at=CHECKED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        (
            "expected_trace_ids",
            "bad",
            "ag.audit_correlation.expected_trace_ids_invalid",
        ),
        (
            "expected_trace_ids",
            [""],
            "ag.audit_correlation.expected_trace_ids_item_invalid",
        ),
        (
            "required_event_types",
            "bad",
            "ag.audit_correlation.required_event_types_invalid",
        ),
        (
            "required_event_types",
            [None],
            "ag.audit_correlation.required_event_types_item_invalid",
        ),
    ],
)
def test_correlation_expectation_lists_are_validated(
    field: str,
    value: object,
    error_code: str,
) -> None:
    kwargs = {field: value, "checked_at": CHECKED_AT}
    with pytest.raises(AuditIntegrityError) as exc_info:
        build_audit_correlation_continuity_report([], **kwargs)  # type: ignore[arg-type]

    assert exc_info.value.error_code == error_code


def test_duplicate_event_id_is_not_projected_twice() -> None:
    event = _event("event-duplicate")

    result = build_audit_correlation_continuity_report(
        [event, deepcopy(event)],
        checked_at=CHECKED_AT,
    )

    assert result["continuity_status"] == "FAILED"
    assert result["summary"]["event_count"] == 1
    assert result["traces"][0]["event_ids"] == ["event-duplicate"]
    assert result["issues"] == [
        {
            "issue_code": "event_integrity_failed",
            "subject_id": None,
            "trace_ids": [],
            "missing_event_types": [],
        }
    ]
