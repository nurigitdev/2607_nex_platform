from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from nex_ag.audit_evidence_api import register_audit_evidence_routes
from nex_ag.audit_evidence_operations import (
    AUDIT_EVIDENCE_OPERATIONS_PATH,
    AUDIT_EVIDENCE_OPERATIONS_SCHEMA_VERSION,
    AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
    AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
    build_audit_evidence_operations_projection,
)
from nex_ag.operations import build_operations_dashboard_snapshot_projection
from nex_ag.operator_reviews import OperatorEvidenceExportStore
from nex_runtime import (
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_operational_event,
    build_service_app,
    issue_mock_user_token,
)


TRACE_ID = "c" * 32
REQUEST_TRACE_ID = "d" * 32
CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def _event(
    event_id: str,
    *,
    event_type: str,
    verification_status: str = "VERIFIED",
    created_at: str = "2026-09-20T07:00:00Z",
    details: dict[str, object] | None = None,
) -> dict[str, Any]:
    safe_details = {
        "package_id": "ag-audit-package-" + "a" * 32,
        "package_hash": "b" * 64,
        "verification_status": verification_status,
        "issue_count": 0,
        "raw_body": "must-not-appear",
    }
    if details is not None:
        safe_details.update(details)
    return build_operational_event(
        service_id="nex-ag",
        event_type=event_type,
        severity="INFO" if verification_status != "FAILED" else "WARNING",
        message="Operations source message must stay private.",
        trace_id=TRACE_ID,
        request_id="request-operations-0866",
        subject_ref={"type": "audit_evidence_package", "id": "source"},
        details=safe_details,
        created_at=created_at,
        event_id=event_id,
    )


def _event_store(*events: dict[str, Any]) -> InMemoryOperationalEventStore:
    store = InMemoryOperationalEventStore()
    for event in events:
        store.append(event)
    return store


def _export(
    export_id: str = "export-0866",
    *,
    evidence_hash: object = "c" * 64,
    updated_at: str = "2026-09-20T07:02:00Z",
) -> dict[str, Any]:
    return {
        "export_id": export_id,
        "trace_id": TRACE_ID,
        "export_status": "READY",
        "evidence_hash": evidence_hash,
        "evidence_item_count": 2,
        "redaction_profile": "ag_redacted_manifest_v1",
        "updated_at": updated_at,
        "evidence_manifest": {"raw_body": "must-not-appear"},
        "operator_ref": {"operator_id": "private-operator"},
    }


def _export_store(*records: dict[str, Any]) -> OperatorEvidenceExportStore:
    store = OperatorEvidenceExportStore()
    for record in records:
        store.save(record)
    return store


def _headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": "request-0866",
        "traceparent": f"00-{REQUEST_TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_operations_projection_is_ready_sorted_bounded_and_redacted() -> None:
    events = _event_store(
        _event(
            "event-generated",
            event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
        ),
        _event(
            "event-verified",
            event_type=AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
            created_at="2026-09-20T07:01:00Z",
        ),
    )
    exports = _export_store(
        _export(),
        _export("export-0866-b", updated_at="2026-09-20T07:03:00Z"),
    )

    result = build_audit_evidence_operations_projection(
        event_store=events,
        export_store=exports,
        recent_limit=1,
        request_trace_id=REQUEST_TRACE_ID,
    )

    assert result["projection_schema_version"] == (
        AUDIT_EVIDENCE_OPERATIONS_SCHEMA_VERSION
    )
    assert result["projection_status"] == "READY"
    assert result["integrity_status"] == "READY"
    assert result["request_trace_id"] == REQUEST_TRACE_ID
    assert result["summary"] == {
        "package_generation_count": 1,
        "package_verification_count": 1,
        "failed_action_count": 0,
        "evidence_export_count": 2,
        "hash_ready_export_count": 2,
        "invalid_hash_export_count": 0,
    }
    assert [item["event_id"] for item in result["recent_actions"]] == [
        "event-verified"
    ]
    assert [item["export_id"] for item in result["recent_exports"]] == [
        "export-0866-b"
    ]
    assert result["paths"]["operations"] == AUDIT_EVIDENCE_OPERATIONS_PATH
    assert result["new_tables_required"] is False
    assert not any(result["redaction"].values())
    serialized = str(result)
    assert "Operations source message must stay private" not in serialized
    assert "must-not-appear" not in serialized
    assert "private-operator" not in serialized


def test_attention_status_detects_failed_actions_and_invalid_export_hashes() -> None:
    result = build_audit_evidence_operations_projection(
        event_store=_event_store(
            _event(
                "event-failed",
                event_type=AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
                verification_status="FAILED",
                details={
                    "package_id": "untrusted-id",
                    "package_hash": "bad",
                    "issue_count": True,
                },
            )
        ),
        export_store=_export_store(_export(evidence_hash="bad")),
    )

    assert result["integrity_status"] == "ATTENTION"
    assert result["summary"]["failed_action_count"] == 1
    assert result["summary"]["invalid_hash_export_count"] == 1
    action = result["recent_actions"][0]
    assert action["package_id"] is None
    assert action["package_hash"] is None
    assert action["issue_count"] is None
    assert result["recent_exports"][0]["evidence_hash"] is None


def test_empty_not_configured_and_service_filtered_states() -> None:
    empty = build_audit_evidence_operations_projection(
        event_store=_event_store(),
        export_store=_export_store(),
    )
    not_configured = build_audit_evidence_operations_projection(
        event_store=_event_store(
            _event(
                "event-only",
                event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
            )
        ),
        export_store=None,
    )
    filtered = build_audit_evidence_operations_projection(
        event_store=_event_store(),
        export_store=_export_store(),
        service_id="nex-cx",
        recent_limit=0,
    )

    assert empty["projection_status"] == "READY"
    assert empty["integrity_status"] == "EMPTY"
    assert not_configured["projection_status"] == "NOT_CONFIGURED"
    assert not_configured["integrity_status"] == "READY"
    assert not_configured["source_statuses"]["evidence_exports"]["status"] == (
        "NOT_CONFIGURED"
    )
    assert filtered["projection_status"] == "READY"
    assert filtered["integrity_status"] == "FILTERED"
    assert filtered["summary"]["evidence_export_count"] == 0
    assert "request_trace_id" not in filtered


class _FailingEventStore:
    def list_events(self, **_: object) -> list[dict[str, Any]]:
        raise RuntimeError("private event database error")


class _FailingExportStore:
    def list_exports(self, **_: object) -> list[dict[str, Any]]:
        raise RuntimeError("private export database error")


def test_source_failures_are_degraded_without_exception_details() -> None:
    event_failed = build_audit_evidence_operations_projection(
        event_store=_FailingEventStore(),  # type: ignore[arg-type]
        export_store=_export_store(),
    )
    export_failed = build_audit_evidence_operations_projection(
        event_store=_event_store(),
        export_store=_FailingExportStore(),
    )

    for result in (event_failed, export_failed):
        assert result["projection_status"] == "DEGRADED"
        assert result["integrity_status"] == "SOURCE_UNAVAILABLE"
        assert "private" not in str(result)
    assert event_failed["source_statuses"]["operational_events"]["error_code"] == (
        "ag.audit_evidence.event_source_unavailable"
    )
    assert export_failed["source_statuses"]["evidence_exports"]["error_code"] == (
        "ag.audit_evidence.export_source_unavailable"
    )


def test_event_projection_normalizes_malformed_optional_details() -> None:
    event = _event(
        "event-malformed",
        event_type=AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
        details={
            "verification_status": "UNKNOWN",
            "package_id": 1,
            "package_hash": None,
            "issue_count": -1,
        },
    )
    event["details"] = "malformed"

    class _RawEventStore:
        def list_events(self, *, event_type: str, **_: object) -> list[dict[str, Any]]:
            return [event] if event["event_type"] == event_type else []

    result = build_audit_evidence_operations_projection(
        event_store=_RawEventStore(),  # type: ignore[arg-type]
        export_store=_export_store(_export(evidence_hash="C" * 64)),
        recent_limit=100,
    )

    action = result["recent_actions"][0]
    assert action["verification_status"] is None
    assert action["package_id"] is None
    assert action["package_hash"] is None
    assert action["issue_count"] is None
    assert result["recent_exports"][0]["evidence_hash"] == "c" * 64


def test_operations_route_is_protected_and_returns_projection() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_audit_evidence_routes(
        app,
        event_store=_event_store(
            _event(
                "event-route",
                event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
            )
        ),
        export_store=_export_store(_export()),
    )
    client = TestClient(app)

    response = client.get(
        AUDIT_EVIDENCE_OPERATIONS_PATH,
        headers=_headers(),
        params={"recent_limit": 1},
    )
    unauthorized = client.get(AUDIT_EVIDENCE_OPERATIONS_PATH)

    assert response.status_code == 200
    assert response.json()["integrity_status"] == "READY"
    assert response.json()["request_trace_id"] == REQUEST_TRACE_ID
    assert unauthorized.status_code == 401


def test_unified_dashboard_contains_audit_integrity_section_and_contract() -> None:
    projection = build_operations_dashboard_snapshot_projection(
        event_store=_event_store(
            _event(
                "event-dashboard",
                event_type=AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
            )
        ),
        operator_review_export_store=_export_store(_export()),
        recent_limit=1,
        request_trace_id=REQUEST_TRACE_ID,
    )
    schema = json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/service/nex_ag/operations_projection.v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert projection["audit_integrity"]["integrity_status"] == "READY"
    assert projection["audit_integrity"]["summary"]["evidence_export_count"] == 1
    Draft202012Validator(schema).validate(projection)
