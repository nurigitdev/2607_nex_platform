from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from nex_ag.generation_quality_disposition import (
    ACTION_STATUS,
    ALLOWED_OPERATOR_ACTIONS,
    DISPOSITION_RECORDED_EVENT_TYPE,
    GenerationQualityDispositionError,
    GenerationQualityDispositionStore,
    build_generation_quality_disposition_record,
    build_generation_quality_disposition_list_response,
    emit_generation_quality_disposition_event,
    find_sensitive_disposition_keys,
    operator_note_preview,
    register_generation_quality_disposition_routes,
    sha256_text,
)
from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventError,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def disposition_schema() -> dict[str, Any]:
    return json.loads(
        (
            CONTRACTS_ROOT
            / "schemas/generation/ag_generation_quality_operator_disposition.v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def sample_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operator_ref": {
            "operator_type": "user",
            "operator_id": "employee-0001",
            "tenant_id": "local-tenant",
        },
        "operator_action": "needs_cx_repair",
        "reason_codes": ["metadata_gap", "user_feedback", "metadata_gap"],
        "operator_note": "CX grounded quality metadata should be restored and replayed.",
        "quality_issue_refs": [
            {
                "source_service": "nex-ag",
                "issue_type": "generation_quality",
                "issue_code": "MISSING_CX_GROUNDED_RESPONSE_QUALITY_FIELDS",
                "issue_ref_id": "cx-gen-001",
            }
        ],
    }
    payload.update(overrides)
    return payload


def build_record(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_generation_quality_disposition_record(
        sample_payload() if payload is None else payload,
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-25T00:00:00Z",
    )


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def build_route_client(
    *,
    store: GenerationQualityDispositionStore | None = None,
    audit_event_store: InMemoryOperationalEventStore | None = None,
) -> tuple[TestClient, GenerationQualityDispositionStore, InMemoryOperationalEventStore]:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    selected_store = store or GenerationQualityDispositionStore()
    selected_event_store = audit_event_store or InMemoryOperationalEventStore()
    register_generation_quality_disposition_routes(
        app,
        store=selected_store,
        audit_event_store=selected_event_store,
    )
    return TestClient(app), selected_store, selected_event_store


def assert_disposition_error(payload: dict[str, Any], error_code: str) -> None:
    with pytest.raises(GenerationQualityDispositionError) as exc:
        build_record(payload)
    assert exc.value.status_code == 422
    assert exc.value.error_code == error_code


def test_generation_quality_disposition_record_matches_contract() -> None:
    record = build_record()

    Draft202012Validator(disposition_schema()).validate(record)
    assert record["disposition_status"] == "IN_REPAIR"
    assert record["reason_codes"] == ["metadata_gap", "user_feedback"]
    assert record["operator_note_hash"] == sha256_text(
        "CX grounded quality metadata should be restored and replayed."
    )
    assert record["operator_note_preview"] == (
        "CX grounded quality metadata should be restored and replayed."
    )
    assert "operator_note" not in record
    assert record["metadata"] == {
        "raw_note_stored": False,
        "raw_prompt_stored": False,
        "raw_generation_output_stored": False,
        "operator_note_storage": "hash_and_short_preview_only",
    }


@pytest.mark.parametrize("operator_action", ALLOWED_OPERATOR_ACTIONS)
def test_operator_actions_map_to_disposition_status(operator_action: str) -> None:
    record = build_record(sample_payload(operator_action=operator_action))

    assert record["operator_action"] == operator_action
    assert record["disposition_status"] == ACTION_STATUS[operator_action]


def test_optional_note_and_refs_can_be_absent() -> None:
    record = build_record(
        sample_payload(
            operator_ref={
                "operator_type": "service",
                "operator_id": "nex-ag",
            },
            operator_note="   ",
            reason_codes=None,
            quality_issue_refs=None,
        )
    )

    Draft202012Validator(disposition_schema()).validate(record)
    assert record["operator_ref"] == {
        "operator_type": "service",
        "operator_id": "nex-ag",
        "tenant_id": None,
    }
    assert record["operator_note_hash"] is None
    assert record["operator_note_preview"] is None
    assert record["reason_codes"] == []
    assert record["quality_issue_refs"] == []


def test_disposition_id_can_be_supplied_or_derived_deterministically() -> None:
    supplied = build_record(sample_payload(disposition_id="operator-choice-001"))
    derived_one = build_record()
    derived_two = build_record()

    assert supplied["disposition_id"] == "operator-choice-001"
    assert derived_one["disposition_id"] == derived_two["disposition_id"]
    assert derived_one["disposition_id"] != supplied["disposition_id"]


def test_operator_note_preview_is_trimmed_and_bounded() -> None:
    note = f"  {'a' * 300}  "

    assert operator_note_preview(note) == "a" * 240


def test_in_memory_store_saves_gets_and_lists_by_generation() -> None:
    store = GenerationQualityDispositionStore()
    first = build_record(sample_payload(disposition_id="disp-001"))
    second = build_generation_quality_disposition_record(
        sample_payload(disposition_id="disp-002", operator_action="resolved"),
        cx_generation_id="cx-gen-002",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-25T00:01:00Z",
    )

    store.save(first)
    store.save(first)
    store.save(second)

    assert store.get("disp-001") == first
    assert store.get("missing") is None
    assert store.list_for_generation("cx-gen-001") == [first]
    assert store.list_for_generation("cx-gen-002") == [second]
    assert store.list_for_generation("cx-gen-missing") == []


def test_disposition_list_response_sorts_and_summarizes_records() -> None:
    older = build_record(
        sample_payload(
            disposition_id="disp-old",
            operator_action="acknowledged",
        )
    )
    newer = build_generation_quality_disposition_record(
        sample_payload(
            disposition_id="disp-new",
            operator_action="resolved",
        ),
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        created_at="2026-08-25T00:10:00Z",
    )

    response = build_generation_quality_disposition_list_response(
        [older, newer],
        cx_generation_id="cx-gen-001",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["disposition_list_schema_version"] == (
        "ag_generation_quality_operator_disposition_list.v1"
    )
    assert [item["disposition_id"] for item in response["items"]] == [
        "disp-new",
        "disp-old",
    ]
    assert response["summary"] == {
        "count": 2,
        "by_status": {"RESOLVED": 1, "ACKNOWLEDGED": 1},
        "latest_updated_at": "2026-08-25T00:10:00Z",
    }


def test_disposition_list_response_handles_empty_records() -> None:
    response = build_generation_quality_disposition_list_response(
        [],
        cx_generation_id="cx-gen-empty",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert response["items"] == []
    assert response["summary"] == {
        "count": 0,
        "by_status": {},
        "latest_updated_at": None,
    }


def test_emit_generation_quality_disposition_event_records_safe_operational_event() -> None:
    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-ag", store=event_store)
    record = build_record(sample_payload(disposition_id="disp-event"))

    result = emit_generation_quality_disposition_event(emitter, record)
    events = event_store.list_events(event_type=DISPOSITION_RECORDED_EVENT_TYPE)

    assert result.ok is True
    assert len(events) == 1
    assert events[0]["subject_ref"] == {
        "type": "generation_quality_disposition",
        "id": "disp-event",
    }
    assert events[0]["details"] == {
        "cx_generation_id": "cx-gen-001",
        "disposition_id": "disp-event",
        "operator_action": "needs_cx_repair",
        "disposition_status": "IN_REPAIR",
        "operator_type": "user",
        "operator_id": "employee-0001",
        "reason_count": 2,
        "quality_issue_ref_count": 1,
    }
    assert "operator_note_preview" not in events[0]["details"]


def test_emit_generation_quality_disposition_event_uses_safe_failure_result() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise OperationalEventError(
                error_code="operational_event.store_unavailable",
                detail="store unavailable",
                status_code=503,
            )

    emitter = OperationalEventEmitter(service_id="nex-ag", store=FailingEventStore())

    result = emit_generation_quality_disposition_event(emitter, build_record())

    assert result.ok is False
    assert result.error_code == "operational_event.store_unavailable"


def test_generation_quality_disposition_routes_create_list_and_get_records() -> None:
    client, store, event_store = build_route_client()

    create_response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
        headers=auth_headers(),
        json=sample_payload(disposition_id="disp-route"),
    )
    list_response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
        headers=auth_headers(),
    )
    get_response = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions/disp-route",
        headers=auth_headers(),
    )

    assert create_response.status_code == 202
    Draft202012Validator(disposition_schema()).validate(create_response.json())
    assert store.get("disp-route") is not None
    assert event_store.summary()["total"] == 1
    assert list_response.status_code == 200
    assert list_response.json()["summary"]["count"] == 1
    assert list_response.json()["items"][0]["disposition_id"] == "disp-route"
    assert get_response.status_code == 200
    assert get_response.json()["disposition_id"] == "disp-route"


def test_generation_quality_disposition_routes_reject_invalid_and_sensitive_payloads() -> None:
    client, _, _ = build_route_client()

    invalid_response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
        headers=auth_headers(),
        json=sample_payload(operator_action="not-supported"),
    )
    sensitive_response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
        headers=auth_headers(),
        json=sample_payload(raw_operator_note="private note"),
    )

    assert invalid_response.status_code == 422
    assert invalid_response.json()["error_code"] == (
        "ag.generation_quality_disposition_operator_action_unsupported"
    )
    assert sensitive_response.status_code == 422
    assert sensitive_response.json()["error_code"] == (
        "ag.generation_quality_disposition_sensitive_payload"
    )


def test_generation_quality_disposition_routes_require_auth_and_hide_cross_generation_records() -> None:
    client, store, _ = build_route_client()
    store.save(build_record(sample_payload(disposition_id="disp-private")))

    unauthorized = client.get(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
    )
    missing = client.get(
        (
            "/admin/v1/generation-audit/generations/cx-gen-other"
            "/quality-dispositions/disp-private"
        ),
        headers=auth_headers(),
    )

    assert unauthorized.status_code == 401
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "ag.generation_quality_disposition_not_found"


def test_generation_quality_disposition_route_still_accepts_when_audit_emit_fails() -> None:
    class FailingEventStore:
        def append(self, event: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("audit unavailable")

    app = build_service_app(SERVICE_SPECS["nex-ag"])
    store = GenerationQualityDispositionStore()
    register_generation_quality_disposition_routes(
        app,
        store=store,
        audit_event_store=FailingEventStore(),
    )
    client = TestClient(app)

    response = client.post(
        "/admin/v1/generation-audit/generations/cx-gen-001/quality-dispositions",
        headers=auth_headers(),
        json=sample_payload(disposition_id="disp-audit-failed"),
    )

    assert response.status_code == 202
    assert store.get("disp-audit-failed") is not None


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        (
            sample_payload(operator_action="unsupported"),
            "ag.generation_quality_disposition_operator_action_unsupported",
        ),
        ({}, "ag.generation_quality_disposition_operator_action_required"),
        (
            sample_payload(operator_ref=None),
            "ag.generation_quality_disposition_operator_ref_required",
        ),
        (
            sample_payload(operator_ref={"operator_type": "bot", "operator_id": "x"}),
            "ag.generation_quality_disposition_operator_type_unsupported",
        ),
        (
            sample_payload(operator_ref={"operator_type": "user", "operator_id": "  "}),
            "ag.generation_quality_disposition_operator_id_required",
        ),
        (
            sample_payload(reason_codes="metadata_gap"),
            "ag.generation_quality_disposition_reasons_invalid",
        ),
        (
            sample_payload(reason_codes=["metadata_gap", ""]),
            "ag.generation_quality_disposition_reason_invalid",
        ),
        (
            sample_payload(reason_codes=["not-a-reason"]),
            "ag.generation_quality_disposition_reason_unsupported",
        ),
        (
            sample_payload(quality_issue_refs="nex-ag"),
            "ag.generation_quality_disposition_quality_refs_invalid",
        ),
        (
            sample_payload(quality_issue_refs=["bad"]),
            "ag.generation_quality_disposition_quality_ref_invalid",
        ),
        (
            sample_payload(
                quality_issue_refs=[
                    {
                        "source_service": "nex-oa",
                        "issue_type": "generation_quality",
                        "issue_code": "x",
                    }
                ]
            ),
            "ag.generation_quality_disposition_source_service_unsupported",
        ),
        (
            sample_payload(
                quality_issue_refs=[
                    {
                        "source_service": "nex-ag",
                        "issue_type": "unknown",
                        "issue_code": "x",
                    }
                ]
            ),
            "ag.generation_quality_disposition_issue_type_unsupported",
        ),
        (
            sample_payload(
                quality_issue_refs=[
                    {
                        "source_service": "nex-ag",
                        "issue_type": "generation_quality",
                        "issue_code": " ",
                    }
                ]
            ),
            "ag.generation_quality_disposition_issue_code_required",
        ),
    ],
)
def test_invalid_disposition_payloads_raise_explicit_errors(
    payload: dict[str, Any],
    error_code: str,
) -> None:
    assert_disposition_error(payload, error_code)


def test_blank_generation_id_is_rejected() -> None:
    with pytest.raises(GenerationQualityDispositionError) as exc:
        build_generation_quality_disposition_record(
            sample_payload(),
            cx_generation_id=" ",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "ag.generation_quality_disposition_cx_generation_id_required"


def test_redaction_guard_allows_operator_note_but_blocks_raw_sensitive_fields() -> None:
    accepted = build_record(sample_payload(operator_note="This note may be previewed."))

    assert accepted["operator_note_preview"] == "This note may be previewed."
    assert_disposition_error(
        sample_payload(raw_operator_note="private full note"),
        "ag.generation_quality_disposition_sensitive_payload",
    )
    assert_disposition_error(
        sample_payload(metadata={"raw_prompt": "private prompt"}),
        "ag.generation_quality_disposition_sensitive_payload",
    )


def test_sensitive_key_finder_reports_nested_paths() -> None:
    payload = {
        "ok": True,
        "items": [
            {"raw_text": "private"},
            {"nested": {"api_key": "secret"}},
        ],
    }

    assert find_sensitive_disposition_keys(payload) == [
        "items[0].raw_text",
        "items[1].nested.api_key",
    ]
