from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nex_ag.audit_evidence_api import (
    AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
    AUDIT_EVIDENCE_PACKAGE_RESPONSE_SCHEMA_VERSION,
    AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
    AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION,
    AuditEvidenceApiError,
    AuditEvidencePackageService,
    register_audit_evidence_routes,
)
from nex_ag.operator_reviews import (
    OperatorEvidenceExportStore,
    OperatorReviewNoteError,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_operational_event,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


SOURCE_TRACE_ID = "a" * 32
REQUEST_TRACE_ID = "b" * 32
REQUEST_ID = "request-0865"


def _event_store() -> InMemoryOperationalEventStore:
    store = InMemoryOperationalEventStore()
    store.append(
        build_operational_event(
            service_id="nex-ag",
            event_type="ag.audit.selected",
            severity="INFO",
            message="API source message must stay private.",
            trace_id=SOURCE_TRACE_ID,
            request_id="source-request-0865",
            subject_ref={"type": "audit_api", "id": "source-0865"},
            details={"credential": "must-redact"},
            created_at="2026-09-20T06:00:00Z",
            event_id="event-0865",
        )
    )
    return store


def _export() -> dict[str, Any]:
    return {
        "export_id": "export-0865",
        "trace_id": SOURCE_TRACE_ID,
        "evidence_hash": "a" * 64,
        "evidence_item_count": 1,
        "export_status": "READY",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {"raw_body": "must-not-appear"},
        "operator_ref": {"operator_id": "employee-private"},
        "updated_at": "2026-09-20T06:01:00Z",
    }


def _export_store() -> OperatorEvidenceExportStore:
    store = OperatorEvidenceExportStore()
    store.save(_export())
    return store


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{REQUEST_TRACE_ID}-00f067aa0ba902b7-01",
    }


def _admin_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    return _headers(issued.access_token)


def _viewer_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    )
    return _headers(issued.access_token)


def _service_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return _headers(issued.access_token)


def _client(
    *,
    event_store: Any | None = None,
    export_store: Any | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
    use_default_audit_store: bool = False,
) -> tuple[TestClient, Any, Any, InMemoryOperationalEventStore]:
    selected_events = event_store or _event_store()
    selected_exports = export_store or _export_store()
    selected_audit = audit_event_store or InMemoryOperationalEventStore()
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    kwargs: dict[str, Any] = {
        "event_store": selected_events,
        "export_store": selected_exports,
    }
    if not use_default_audit_store:
        kwargs["audit_event_store"] = selected_audit
    register_audit_evidence_routes(app, **kwargs)
    return TestClient(app), selected_events, selected_exports, selected_audit


def _create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "trace_id": SOURCE_TRACE_ID,
        "expected_event_ids": ["event-0865", "event-0865"],
        "required_event_types": ["ag.audit.selected", "ag.audit.selected"],
    }
    payload.update(overrides)
    return payload


def test_service_selects_server_records_and_returns_verified_package() -> None:
    service = AuditEvidencePackageService(
        event_store=_event_store(),
        export_store=_export_store(),
    )

    result = service.create_package(
        _create_payload(),
        request_id=REQUEST_ID,
        request_trace_id=REQUEST_TRACE_ID,
    )

    assert result["response_schema_version"] == (
        AUDIT_EVIDENCE_PACKAGE_RESPONSE_SCHEMA_VERSION
    )
    assert result["source_trace_id"] == SOURCE_TRACE_ID
    assert result["selection"] == {
        "server_selected": True,
        "event_count": 1,
        "evidence_export_count": 1,
        "expected_event_count": 1,
        "required_event_type_count": 1,
    }
    assert result["package"]["verification_status"] == "VERIFIED"
    assert result["verification"]["verification_status"] == "VERIFIED"
    serialized = str(result)
    assert "API source message must stay private" not in serialized
    assert "must-redact" not in serialized
    assert "must-not-appear" not in serialized
    assert "employee-private" not in serialized


def test_admin_create_and_verify_routes_emit_safe_audit_events() -> None:
    audit_store = InMemoryOperationalEventStore()
    client, _, _, _ = _client(audit_event_store=audit_store)

    created_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=_admin_headers(),
        json=_create_payload(),
    )
    created = created_response.json()
    verified_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        headers=_admin_headers(),
        json={"package": created["package"]},
    )

    assert created_response.status_code == 200
    assert verified_response.status_code == 200
    verified = verified_response.json()
    assert verified["response_schema_version"] == (
        AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION
    )
    assert verified["request_id"] == REQUEST_ID
    assert verified["request_trace_id"] == REQUEST_TRACE_ID
    assert verified["verification"]["verification_status"] == "VERIFIED"
    events = audit_store.list_events(limit=10)
    assert {event["event_type"] for event in events} == {
        AUDIT_EVIDENCE_PACKAGE_GENERATED_EVENT_TYPE,
        AUDIT_EVIDENCE_PACKAGE_VERIFIED_EVENT_TYPE,
    }
    assert all(event["trace_id"] == REQUEST_TRACE_ID for event in events)
    serialized = str(events)
    assert "manifest" not in serialized
    assert "raw_body" not in serialized


def test_service_principal_is_allowed_and_default_audit_store_is_used() -> None:
    client, event_store, _, _ = _client(use_default_audit_store=True)

    response = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=_service_headers(),
        json=_create_payload(),
    )

    assert response.status_code == 200
    assert len(event_store.list_events(limit=10)) == 2


def test_non_admin_user_and_missing_token_are_rejected() -> None:
    client, _, _, _ = _client()

    forbidden = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=_viewer_headers(),
        json=_create_payload(),
    )
    unauthorized = client.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        json={"package": {}},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == (
        "AG_AUDIT_EVIDENCE_ADMIN_ROLE_REQUIRED"
    )
    assert unauthorized.status_code == 401


def test_verify_route_does_not_echo_tampered_package_and_emits_warning() -> None:
    audit_store = InMemoryOperationalEventStore()
    client, _, _, _ = _client(audit_event_store=audit_store)
    tampered = {"package_id": "private-id", "secret": "must-not-echo"}

    response = client.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        headers=_admin_headers(),
        json={"package": tampered},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["verification_status"] == "FAILED"
    assert body["verification"]["package_id"] is None
    assert "package" not in body
    assert "must-not-echo" not in str(body)
    assert "private-id" not in str(body)
    event = audit_store.list_events(limit=1)[0]
    assert event["severity"] == "WARNING"
    assert event["subject_ref"]["id"] == "unknown"
    assert "private-id" not in str(event)


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (
            {"trace_id": SOURCE_TRACE_ID, "events": []},
            "ag.audit_evidence.create_fields_unsupported",
        ),
        ({}, "ag.audit_evidence.trace_id_required"),
        ({"trace_id": 1}, "ag.audit_evidence.trace_id_required"),
        (
            {"trace_id": SOURCE_TRACE_ID, "expected_event_ids": "bad"},
            "ag.audit_evidence.expected_event_ids_invalid",
        ),
        (
            {"trace_id": SOURCE_TRACE_ID, "expected_event_ids": [""]},
            "ag.audit_evidence.expected_event_ids_item_invalid",
        ),
        (
            {"trace_id": SOURCE_TRACE_ID, "required_event_types": [None]},
            "ag.audit_evidence.required_event_types_item_invalid",
        ),
    ],
)
def test_create_payload_guardrails(
    payload: dict[str, object],
    error_code: str,
) -> None:
    service = AuditEvidencePackageService(
        event_store=_event_store(),
        export_store=_export_store(),
    )

    with pytest.raises(AuditEvidenceApiError) as exc_info:
        service.create_package(
            payload,
            request_id=REQUEST_ID,
            request_trace_id=None,
        )

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_failed_expectations_return_a_self_verifying_failed_package() -> None:
    service = AuditEvidencePackageService(
        event_store=_event_store(),
        export_store=_export_store(),
    )

    result = service.create_package(
        {
            "trace_id": SOURCE_TRACE_ID,
            "expected_event_ids": ["missing-event"],
            "required_event_types": ["ag.audit.missing"],
        },
        request_id=REQUEST_ID,
        request_trace_id=None,
    )

    assert result["package"]["verification_status"] == "FAILED"
    assert result["verification"]["verification_status"] == "VERIFIED"


def test_verify_payload_requires_exact_package_field() -> None:
    service = AuditEvidencePackageService(
        event_store=_event_store(),
        export_store=_export_store(),
    )

    for payload in ({}, {"package": {}, "extra": True}):
        with pytest.raises(AuditEvidenceApiError) as exc_info:
            service.verify_package(
                payload,
                request_id=REQUEST_ID,
                request_trace_id=None,
            )
        assert exc_info.value.error_code == (
            "ag.audit_evidence.verify_payload_invalid"
        )


def test_route_maps_create_and_verify_payload_errors_to_problem_details() -> None:
    client, _, _, _ = _client()

    create_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=_admin_headers(),
        json={"trace_id": ""},
    )
    verify_response = client.post(
        "/admin/v1/audit-integrity/evidence-packages/verify",
        headers=_admin_headers(),
        json={"unexpected": {}},
    )

    assert create_response.status_code == 422
    assert create_response.json()["error_code"] == (
        "ag.audit_evidence.trace_id_required"
    )
    assert verify_response.status_code == 422
    assert verify_response.json()["error_code"] == (
        "ag.audit_evidence.verify_payload_invalid"
    )


class _UnavailableExportStore:
    def list_exports(self, **_: object) -> list[dict[str, object]]:
        raise OperatorReviewNoteError(
            status_code=503,
            error_code="ag.evidence_export_store_unavailable",
            detail="Operator evidence export store is unavailable.",
        )


def test_route_maps_store_failure_without_emitting_an_event() -> None:
    audit_store = InMemoryOperationalEventStore()
    client, _, _, _ = _client(
        export_store=_UnavailableExportStore(),
        audit_event_store=audit_store,
    )

    response = client.post(
        "/admin/v1/audit-integrity/evidence-packages",
        headers=_admin_headers(),
        json=_create_payload(),
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == (
        "ag.evidence_export_store_unavailable"
    )
    assert audit_store.list_events(limit=10) == []


def test_verify_service_returns_safe_result_only() -> None:
    service = AuditEvidencePackageService(
        event_store=_event_store(),
        export_store=_export_store(),
    )
    created = service.create_package(
        _create_payload(),
        request_id=REQUEST_ID,
        request_trace_id=REQUEST_TRACE_ID,
    )
    package = deepcopy(created["package"])

    result = service.verify_package(
        {"package": package},
        request_id=REQUEST_ID,
        request_trace_id=REQUEST_TRACE_ID,
    )

    assert result["response_schema_version"] == (
        AUDIT_EVIDENCE_VERIFY_RESPONSE_SCHEMA_VERSION
    )
    assert result["verification"]["verification_status"] == "VERIFIED"
    assert "package" not in result
