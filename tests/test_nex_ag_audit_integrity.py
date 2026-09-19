from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ag.audit_integrity import (
    AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION,
    MAX_AUDIT_INTEGRITY_EVENTS,
    AuditIntegrityError,
    build_audit_event_integrity_report,
    sha256_canonical_json,
)
from nex_runtime.operational_events import build_operational_event


CHECKED_AT = "2026-09-20T01:00:00Z"


def _event(
    event_id: str,
    *,
    created_at: str = "2026-09-20T00:00:00Z",
    with_refs: bool = True,
) -> dict[str, object]:
    return build_operational_event(
        service_id="nex-ag",
        event_type="ag.audit.tested",
        severity="INFO",
        message="Audit integrity test event.",
        trace_id="trace-0862" if with_refs else None,
        request_id="request-0862" if with_refs else None,
        subject_ref={"type": "audit_test", "id": "subject-0862"}
        if with_refs
        else None,
        details={"safe_count": 1, "provider_token": "must-redact"},
        created_at=created_at,
        event_id=event_id,
    )


def test_integrity_report_is_deterministic_sorted_and_redacted() -> None:
    later = _event(
        "event-later",
        created_at="2026-09-20T01:30:00+01:00",
        with_refs=False,
    )
    earlier = _event("event-earlier", created_at="2026-09-20T00:00:00Z")
    original = deepcopy([later, earlier])

    result = build_audit_event_integrity_report(
        [later, earlier],
        checked_at=CHECKED_AT,
    )
    repeated = build_audit_event_integrity_report(
        [earlier, later],
        checked_at="2026-09-20T02:00:00Z",
    )

    assert result["integrity_report_schema_version"] == (
        AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION
    )
    assert result["integrity_status"] == "VERIFIED"
    assert result["summary"] == {
        "observed_count": 2,
        "verified_item_count": 2,
        "valid_count": 2,
        "invalid_count": 0,
        "duplicate_event_id_count": 0,
        "missing_expected_count": 0,
        "hash_mismatch_count": 0,
        "issue_count": 0,
    }
    assert [item["event_id"] for item in result["items"]] == [
        "event-earlier",
        "event-later",
    ]
    assert result["items"][0]["trace_id_present"] is True
    assert result["items"][0]["request_id_present"] is True
    assert result["items"][0]["subject_ref_present"] is True
    assert result["items"][1]["trace_id_present"] is False
    assert result["items"][1]["request_id_present"] is False
    assert result["items"][1]["subject_ref_present"] is False
    assert result["report_hash"] == repeated["report_hash"]
    assert [later, earlier] == original
    serialized = str(result)
    assert "Audit integrity test event" not in serialized
    assert "safe_count" not in serialized
    assert "must-redact" not in serialized


def test_empty_report_and_default_checked_at() -> None:
    result = build_audit_event_integrity_report([])

    assert result["integrity_status"] == "NO_EVENTS"
    assert result["checked_at"].endswith("Z")
    assert result["summary"]["observed_count"] == 0


def test_missing_expected_events_are_reported_and_deduplicated() -> None:
    result = build_audit_event_integrity_report(
        [_event("event-present")],
        expected_event_ids=["event-missing", "event-present", "event-missing"],
        checked_at=CHECKED_AT,
    )

    assert result["integrity_status"] == "FAILED"
    assert result["expected_events"] == {
        "event_ids": ["event-missing", "event-present"],
        "expected_count": 2,
        "all_present": False,
    }
    assert result["summary"]["missing_expected_count"] == 1
    assert result["issues"][0]["issue_code"] == "expected_event_missing"


def test_duplicate_non_object_and_invalid_events_are_reported() -> None:
    valid = _event("event-duplicate")
    missing_field = _event("event-invalid")
    missing_field.pop("severity")
    result = build_audit_event_integrity_report(
        [valid, deepcopy(valid), "not-an-event", missing_field],  # type: ignore[list-item]
        checked_at=CHECKED_AT,
    )

    assert result["integrity_status"] == "FAILED"
    assert result["summary"]["verified_item_count"] == 1
    assert result["summary"]["duplicate_event_id_count"] == 1
    assert result["summary"]["invalid_count"] == 2
    assert {item["issue_code"] for item in result["issues"]} == {
        "duplicate_event_id",
        "event_invalid",
        "event_not_object",
    }


@pytest.mark.parametrize(
    ("created_at", "error_code"),
    [
        ("not-a-date", "ag.audit_integrity.created_at_invalid"),
        ("2026-09-20T00:00:00", "ag.audit_integrity.created_at_timezone_required"),
    ],
)
def test_invalid_event_timestamps_are_reported(
    created_at: str,
    error_code: str,
) -> None:
    event = _event("event-time")
    event["created_at"] = created_at

    result = build_audit_event_integrity_report(
        [event],
        checked_at=CHECKED_AT,
    )

    assert result["integrity_status"] == "FAILED"
    assert result["issues"][0]["error_code"] == error_code


def test_expected_hash_match_and_mismatch_are_verified() -> None:
    event = _event("event-hash")
    observed_hash = sha256_canonical_json(event)
    matched = build_audit_event_integrity_report(
        [event],
        expected_event_hashes={"event-hash": observed_hash.upper()},
        checked_at=CHECKED_AT,
    )
    mismatched = build_audit_event_integrity_report(
        [event],
        expected_event_hashes={"event-hash": "0" * 64},
        checked_at=CHECKED_AT,
    )

    assert matched["integrity_status"] == "VERIFIED"
    assert matched["items"][0]["integrity_status"] == "VALID"
    assert mismatched["integrity_status"] == "FAILED"
    assert mismatched["items"][0]["integrity_status"] == "HASH_MISMATCH"
    assert mismatched["summary"]["hash_mismatch_count"] == 1
    assert mismatched["summary"]["valid_count"] == 0


def test_canonical_json_hash_ignores_mapping_order() -> None:
    assert sha256_canonical_json({"b": 2, "a": 1}) == sha256_canonical_json(
        {"a": 1, "b": 2}
    )


def test_event_collection_shape_and_limit_are_validated() -> None:
    with pytest.raises(AuditIntegrityError) as invalid:
        build_audit_event_integrity_report("bad")  # type: ignore[arg-type]
    with pytest.raises(AuditIntegrityError) as exceeded:
        build_audit_event_integrity_report(
            [{} for _ in range(MAX_AUDIT_INTEGRITY_EVENTS + 1)]
        )

    assert invalid.value.error_code == "ag.audit_integrity.events_invalid"
    assert exceeded.value.error_code == (
        "ag.audit_integrity.events_limit_exceeded"
    )
    assert str(invalid.value) == "events must be a list."


@pytest.mark.parametrize(
    ("value", "error_code"),
    [
        ("bad", "ag.audit_integrity.expected_event_ids_invalid"),
        ([""], "ag.audit_integrity.expected_event_id_invalid"),
        ([None], "ag.audit_integrity.expected_event_id_invalid"),
    ],
)
def test_expected_event_ids_are_validated(value: object, error_code: str) -> None:
    with pytest.raises(AuditIntegrityError) as exc_info:
        build_audit_event_integrity_report(
            [],
            expected_event_ids=value,  # type: ignore[arg-type]
            checked_at=CHECKED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("value", "error_code"),
    [
        ([], "ag.audit_integrity.expected_hashes_invalid"),
        ({"": "0" * 64}, "ag.audit_integrity.expected_hash_invalid"),
        ({"event": None}, "ag.audit_integrity.expected_hash_invalid"),
        ({"event": "bad"}, "ag.audit_integrity.expected_hash_invalid"),
    ],
)
def test_expected_hashes_are_validated(value: object, error_code: str) -> None:
    with pytest.raises(AuditIntegrityError) as exc_info:
        build_audit_event_integrity_report(
            [],
            expected_event_hashes=value,  # type: ignore[arg-type]
            checked_at=CHECKED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("checked_at", "error_code"),
    [
        ("bad", "ag.audit_integrity.checked_at_invalid"),
        ("2026-09-20T00:00:00", "ag.audit_integrity.checked_at_timezone_required"),
    ],
)
def test_checked_at_is_validated(checked_at: str, error_code: str) -> None:
    with pytest.raises(AuditIntegrityError) as exc_info:
        build_audit_event_integrity_report([], checked_at=checked_at)

    assert exc_info.value.error_code == error_code
