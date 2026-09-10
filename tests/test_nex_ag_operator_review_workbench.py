from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
import pytest

from nex_ag.operator_review_workbench import (
    OPERATOR_REVIEW_WORKBENCH_ROLLUP_SCHEMA_VERSION,
    OPERATOR_REVIEW_WORKBENCH_SCHEMA_VERSION,
    build_operator_review_workbench_projection,
    build_operator_review_workbench_projection_from_stores,
    build_operator_review_workbench_rollup_metrics,
    normalize_operator_review_workbench_filters,
    register_operator_review_workbench_routes,
)
from nex_ag.operator_reviews import (
    OperatorEvidenceExportStore,
    OperatorReviewNoteError,
    OperatorReviewNoteStore,
    build_operator_evidence_export_record,
    build_operator_review_note_record,
    sha256_text,
)
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def note_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_ref": {
            "target_service": "nex-ae-api",
            "target_kind": "operator_control.worker_result",
            "target_id": "worker-result-001",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "operator_note": "Worker result needs review before closing.",
        "note_type": "OBSERVATION",
        "severity": "HIGH",
        "reason_codes": ["worker_result_attention"],
        "metadata": {
            "idempotency_key_hash": "hidden-hash",
            "source_view": "operations_dashboard",
        },
    }
    payload.update(overrides)
    return payload


def export_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_ref": {
            "target_service": "nex-ae-api",
            "target_kind": "operator_control.worker_result",
            "target_id": "worker-result-001",
        },
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "export_status": "READY",
        "export_format": "json",
        "evidence_refs": [
            {
                "source_service": "nex-ae-api",
                "evidence_type": "worker_result",
                "evidence_id": "worker-result-001",
                "content_hash": "a" * 64,
                "redaction_status": "HASH_ONLY",
            }
        ],
        "metadata": {
            "idempotency_key_hash": "hidden-export-hash",
            "source_view": "operations_dashboard",
        },
    }
    payload.update(overrides)
    return payload


def build_note(
    *,
    payload: dict[str, Any] | None = None,
    created_at: str = "2026-09-10T00:00:00Z",
) -> dict[str, Any]:
    return build_operator_review_note_record(
        note_payload() if payload is None else payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=f"note-{created_at}",
        created_at=created_at,
    )


def build_export(
    *,
    payload: dict[str, Any] | None = None,
    created_at: str = "2026-09-10T00:05:00Z",
) -> dict[str, Any]:
    return build_operator_evidence_export_record(
        export_payload() if payload is None else payload,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=f"export-{created_at}",
        created_at=created_at,
    )


def service_auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def admin_auth_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def viewer_auth_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    )
    return {"Authorization": f"Bearer {issued.access_token}"}


def route_client() -> tuple[TestClient, OperatorReviewNoteStore, OperatorEvidenceExportStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    register_operator_review_workbench_routes(
        app,
        note_store=note_store,
        export_store=export_store,
    )
    return TestClient(app), note_store, export_store


def test_workbench_projection_groups_notes_and_exports_by_target() -> None:
    note = build_note()
    export = build_export()
    projection = build_operator_review_workbench_projection(
        [note],
        [export],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        filters=normalize_operator_review_workbench_filters(target_service="nex-ae-api"),
    )

    assert projection["workbench_schema_version"] == OPERATOR_REVIEW_WORKBENCH_SCHEMA_VERSION
    assert projection["summary"] == {
        "target_count": 1,
        "note_count": 1,
        "export_count": 1,
        "open_note_count": 1,
        "failed_export_count": 0,
        "latest_updated_at": "2026-09-10T00:05:00Z",
    }
    item = projection["items"][0]
    assert item["target_ref"] == {
        "target_service": "nex-ae-api",
        "target_kind": "operator_control.worker_result",
        "target_id": "worker-result-001",
    }
    assert item["trace_ids"] == [TRACE_ID]
    assert item["note_summary"]["by_status"] == {"ACTIVE": 1}
    assert item["note_summary"]["by_severity"] == {"HIGH": 1}
    assert item["export_summary"]["by_status"] == {"READY": 1}
    assert item["export_summary"]["evidence_item_count"] == 1
    assert item["notes"][0]["operator_note_hash"] == sha256_text(
        "Worker result needs review before closing."
    )
    assert item["notes"][0]["operator_note_preview"] == (
        "Worker result needs review before closing."
    )
    assert item["evidence_exports"][0]["evidence_hash"] == export["evidence_hash"]
    serialized = json.dumps(projection, ensure_ascii=False)
    assert "hidden-hash" not in serialized
    assert "hidden-export-hash" not in serialized
    assert "idempotency_key_hash" not in serialized


def test_workbench_projection_sorts_targets_by_latest_update() -> None:
    older_note = build_note(created_at="2026-09-10T00:00:00Z")
    newer_note = build_note(
        payload=note_payload(
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
            severity="LOW",
        ),
        created_at="2026-09-10T00:10:00Z",
    )

    projection = build_operator_review_workbench_projection(
        [older_note, newer_note],
        [],
        request_id=REQUEST_ID,
        trace_id=None,
    )

    assert [item["target_ref"]["target_service"] for item in projection["items"]] == [
        "nex-cx",
        "nex-ae-api",
    ]
    assert projection["summary"]["target_count"] == 2
    assert projection["redaction"]["raw_operator_note_included"] is False


def test_workbench_projection_from_stores_applies_filters() -> None:
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    matching_note = build_note()
    note_store.save(matching_note)
    note_store.save(
        build_note(
            payload=note_payload(
                target_ref={
                    "target_service": "nex-cx",
                    "target_kind": "processing_run",
                    "target_id": "cx-run-001",
                }
            ),
            created_at="2026-09-10T00:20:00Z",
        )
    )
    export_store.save(build_export())

    projection = build_operator_review_workbench_projection_from_stores(
        note_store=note_store,
        export_store=export_store,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        target_service="nex-ae-api",
        operator_type="user",
        operator_id="employee-0001",
    )

    assert projection["summary"]["target_count"] == 1
    assert projection["summary"]["note_count"] == 1
    assert projection["summary"]["export_count"] == 1
    assert projection["filters"]["target_service"] == "nex-ae-api"
    assert projection["items"][0]["notes"][0]["operator_note_id"] == (
        matching_note["operator_note_id"]
    )


def test_workbench_route_allows_service_and_admin_tokens() -> None:
    client, note_store, export_store = route_client()
    note_store.save(build_note())
    export_store.save(build_export())

    service_response = client.get(
        "/admin/v1/operator-review/workbench",
        headers=service_auth_headers(),
    )
    assert service_response.status_code == 200
    assert service_response.json()["summary"]["target_count"] == 1

    admin_response = client.get(
        "/admin/v1/operator-review/workbench?target_service=nex-ae-api",
        headers=admin_auth_headers(),
    )
    assert admin_response.status_code == 200
    assert admin_response.json()["filters"]["target_service"] == "nex-ae-api"


def test_workbench_route_rejects_auth_and_invalid_filters() -> None:
    client, _note_store, _export_store = route_client()

    assert client.get("/admin/v1/operator-review/workbench").status_code == 401
    assert (
        client.get(
            "/admin/v1/operator-review/workbench",
            headers=viewer_auth_headers(),
        ).status_code
        == 403
    )
    invalid = client.get(
        "/admin/v1/operator-review/workbench?target_service=bad-service",
        headers=service_auth_headers(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ag.operator_review_note_target_service_unsupported"
    )


def test_workbench_helpers_cover_empty_and_invalid_inputs() -> None:
    projection = build_operator_review_workbench_projection(
        [],
        [],
        request_id=REQUEST_ID,
        trace_id=None,
    )
    assert projection["summary"] == {
        "target_count": 0,
        "note_count": 0,
        "export_count": 0,
        "open_note_count": 0,
        "failed_export_count": 0,
        "latest_updated_at": None,
    }
    assert projection["items"] == []

    with pytest.raises(OperatorReviewNoteError):
        normalize_operator_review_workbench_filters(target_service="bad-service")


def test_workbench_projection_handles_missing_operator_ref_defensively() -> None:
    note = build_note()
    note["operator_ref"] = None

    projection = build_operator_review_workbench_projection(
        [note],
        [],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert projection["items"][0]["notes"][0]["operator_ref"] == {
        "operator_type": None,
        "operator_id": None,
        "tenant_id": None,
    }


def test_workbench_rollup_metrics_summarize_attention() -> None:
    high_note = build_note()
    resolved_note = build_note(
        payload=note_payload(
            note_status="RESOLVED",
            severity="LOW",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
        ),
        created_at="2026-09-10T00:10:00Z",
    )
    failed_export = build_export(
        payload=export_payload(
            export_status="FAILED",
            target_ref={
                "target_service": "nex-cx",
                "target_kind": "processing_run",
                "target_id": "cx-run-001",
            },
        ),
        created_at="2026-09-10T00:15:00Z",
    )
    projection = build_operator_review_workbench_projection(
        [high_note, resolved_note],
        [failed_export],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    rollup = build_operator_review_workbench_rollup_metrics(projection)

    assert rollup["rollup_schema_version"] == OPERATOR_REVIEW_WORKBENCH_ROLLUP_SCHEMA_VERSION
    assert rollup["summary"] == {
        "target_count": 2,
        "note_count": 2,
        "export_count": 1,
        "open_note_count": 1,
        "resolved_note_count": 1,
        "deleted_note_count": 0,
        "high_urgency_note_count": 1,
        "ready_export_count": 0,
        "failed_export_count": 1,
        "evidence_item_count": 1,
        "attention_target_count": 2,
    }
    assert rollup["by_target_service"] == {"nex-ae-api": 1, "nex-cx": 1}
    assert rollup["by_note_status"] == {"ACTIVE": 1, "RESOLVED": 1}
    assert rollup["by_export_status"] == {"FAILED": 1}
    assert rollup["attention"]["by_status"] == {"ATTENTION": 1, "BLOCKED": 1}
    assert rollup["attention"]["items"][0]["attention_status"] == "BLOCKED"
    assert "failed_evidence_export" in rollup["attention"]["items"][0]["reason_codes"]
    serialized = json.dumps(rollup, ensure_ascii=False)
    assert "idempotency_key_hash" not in serialized
    assert rollup["redaction"]["raw_evidence_body_included"] is False


def test_workbench_rollup_route_uses_same_auth_and_filters() -> None:
    client, note_store, export_store = route_client()
    note_store.save(build_note())
    export_store.save(build_export())

    assert client.get("/admin/v1/operator-review/workbench/rollups").status_code == 401

    response = client.get(
        "/admin/v1/operator-review/workbench/rollups?target_service=nex-ae-api",
        headers=service_auth_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rollup_schema_version"] == OPERATOR_REVIEW_WORKBENCH_ROLLUP_SCHEMA_VERSION
    assert body["filters"]["target_service"] == "nex-ae-api"
    assert body["summary"]["attention_target_count"] == 1
    assert body["attention"]["items"][0]["attention_status"] == "ATTENTION"

    invalid = client.get(
        "/admin/v1/operator-review/workbench/rollups?target_service=bad-service",
        headers=admin_auth_headers(),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == (
        "ag.operator_review_note_target_service_unsupported"
    )


def test_workbench_rollup_empty_projection_is_safe() -> None:
    projection = build_operator_review_workbench_projection(
        [],
        [],
        request_id=REQUEST_ID,
        trace_id=None,
    )

    rollup = build_operator_review_workbench_rollup_metrics(projection)

    assert rollup["summary"]["target_count"] == 0
    assert rollup["summary"]["attention_target_count"] == 0
    assert rollup["attention"] == {"items": [], "by_status": {}}
    assert rollup["by_target_service"] == {}


def test_workbench_rollup_open_and_ok_attention_branches() -> None:
    low_active_note = build_note(
        payload=note_payload(severity="LOW"),
        created_at="2026-09-10T00:10:00Z",
    )
    resolved_note = build_note(
        payload=note_payload(
            note_status="RESOLVED",
            severity="URGENT",
            target_ref={
                "target_service": "nex-mo",
                "target_kind": "provider",
                "target_id": "embedding-provider",
            },
        ),
        created_at="2026-09-10T00:20:00Z",
    )
    projection = build_operator_review_workbench_projection(
        [low_active_note, resolved_note],
        [],
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    rollup = build_operator_review_workbench_rollup_metrics(projection)

    assert rollup["summary"]["attention_target_count"] == 1
    assert rollup["attention"]["items"] == [
        {
            "target_ref": {
                "target_service": "nex-ae-api",
                "target_kind": "operator_control.worker_result",
                "target_id": "worker-result-001",
            },
            "attention_status": "OPEN",
            "reason_codes": ["active_operator_note"],
            "note_count": 1,
            "export_count": 0,
            "latest_updated_at": "2026-09-10T00:10:00Z",
        }
    ]
    assert rollup["by_note_severity"] == {"LOW": 1, "URGENT": 1}
