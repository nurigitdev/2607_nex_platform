#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.operations import register_unified_operation_routes  # noqa: E402
from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    OperatorReviewEscalationDispatchStore,
    OperatorReviewEscalationStore,
    build_operator_review_escalation_record,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import OperatorReviewNoteError  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ag_operator_review_escalation_dispatch_privacy_regression.v1"
SLICE_ID = "0709"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_dispatch_privacy"
TARGET_ID = "operator-review-escalation-dispatch-privacy-0709"
CASE_ID = "case-operator-review-escalation-dispatch-privacy-0709"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
REFERENCE_TIME = "2026-09-12T13:00:00Z"

RAW_PROVIDER_PAYLOAD = "RAW_PROVIDER_PAYLOAD_0709_SHOULD_NOT_LEAK"
RAW_NOTIFICATION_PAYLOAD = "RAW_NOTIFICATION_PAYLOAD_0709_SHOULD_NOT_LEAK"
RAW_EXTERNAL_INCIDENT_PAYLOAD = "RAW_EXTERNAL_INCIDENT_0709_SHOULD_NOT_LEAK"
RAW_ACTION_COMMENT = "RAW_ACTION_SECRET_0709_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0709_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0709_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/dispatch-0709.pdf"
DISPATCH_IDEMPOTENCY_KEY = "idem-0709-dispatch-secret"
ACTION_IDEMPOTENCY_KEY = "idem-0709-dispatch-action-secret"
ESCALATION_IDEMPOTENCY_KEY = "idem-0709-escalation-secret"
PROVIDER_API_KEY = "provider-key-0709"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0709"
SAFE_SUBJECT = "Dispatch privacy regression owner notification."
SAFE_BODY = "Safe bounded dispatch body for privacy regression."
SAFE_ACTION_COMMENT = "Dispatch attempt started for privacy regression."

FORBIDDEN_VALUES = {
    "raw_provider_payload": RAW_PROVIDER_PAYLOAD,
    "raw_notification_payload": RAW_NOTIFICATION_PAYLOAD,
    "raw_external_incident_payload": RAW_EXTERNAL_INCIDENT_PAYLOAD,
    "raw_action_comment": RAW_ACTION_COMMENT,
    "raw_prompt": RAW_PROMPT,
    "raw_source_text": RAW_SOURCE_TEXT,
    "storage_path": STORAGE_PATH,
    "dispatch_idempotency_key": DISPATCH_IDEMPOTENCY_KEY,
    "action_idempotency_key": ACTION_IDEMPOTENCY_KEY,
    "escalation_idempotency_key": ESCALATION_IDEMPOTENCY_KEY,
    "provider_api_key": PROVIDER_API_KEY,
    "database_url": DATABASE_URL,
    "service_token": SERVICE_TOKEN,
}

FORBIDDEN_KEYS = {
    "action_comment",
    "database_url",
    "external_incident_payload",
    "idempotency_key",
    "notification_payload",
    "provider_api_key",
    "provider_payload",
    "raw_action_comment",
    "raw_external_incident_payload",
    "raw_notification_payload",
    "raw_prompt",
    "raw_provider_payload",
    "raw_source_text",
    "secret",
    "service_token",
    "storage_path",
    "storage_uri",
}

SENSITIVE_REDACTION_FLAGS = {
    "database_urls_included",
    "external_incident_payload_included",
    "idempotency_keys_included",
    "notification_payload_included",
    "provider_payloads_included",
    "provider_secrets_included",
    "raw_action_comment_included",
    "raw_external_incident_payload_included",
    "raw_notification_payload_included",
    "raw_operator_comments_included",
    "raw_provider_error_included",
    "raw_provider_payload_included",
    "raw_prompt_included",
    "raw_source_text_included",
    "storage_paths_included",
    "tokens_included",
}


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_escalation_dispatch_privacy_regression() -> dict[str, Any]:
    stores = _build_fixture_stores()
    case_store, escalation_store, dispatch_store, event_store, escalation_id = stores
    client = _build_client(case_store, escalation_store, dispatch_store, event_store)
    create_surface = _create_dispatch_surface(client, escalation_id)
    dispatch_id = _created_dispatch_id(create_surface.payload)
    surfaces = [
        create_surface,
        *_collect_dispatch_read_surfaces(client, dispatch_id),
        _apply_dispatch_action_surface(client, dispatch_id),
    ]
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    surface_map = {surface.name: surface.payload for surface in surfaces}
    checks = {
        "all_routes_successful": all(
            surface.status_code in {200, 201} for surface in surfaces
        ),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "raw_fields_absent": all(
            not _contains_forbidden_keys(surface.payload, FORBIDDEN_KEYS)
            for surface in surfaces
        ),
        "redaction_flags_safe": all(
            _redaction_flags_safe(surface.payload) for surface in surfaces
        ),
        "create_plan_surface_ready": (
            surface_map["dispatch_plan"].get("dispatch_plan_schema_version")
            == "ag_operator_review_escalation_dispatch_plan.v1"
            and surface_map["dispatch_plan"].get("idempotency_status") == "NEW"
            and surface_map["dispatch_plan"]
            .get("dispatch_record", {})
            .get("dispatch_status")
            == "PENDING"
        ),
        "list_surface_ready": (
            surface_map["dispatch_list"].get("dispatch_list_schema_version")
            == "ag_operator_review_escalation_dispatch_list.v1"
            and surface_map["dispatch_list"].get("summary", {}).get("count") == 1
        ),
        "detail_surface_ready": (
            surface_map["dispatch_detail"].get("dispatch_schema_version")
            == "ag_operator_review_escalation_dispatch.v1"
            and surface_map["dispatch_detail"].get("dispatch_status") == "PENDING"
        ),
        "dashboard_surface_ready": _dashboard_dispatch_summary_safe(
            surface_map["dashboard"]
        ),
        "issue_candidate_surface_ready": _issue_candidate_surface_safe(
            surface_map["issue_candidates"]
        ),
        "action_surface_ready": (
            surface_map["action_mutation"].get(
                "dispatch_action_mutation_schema_version"
            )
            == "ag_operator_review_escalation_dispatch_action_mutation.v1"
            and surface_map["action_mutation"].get("idempotency_status") == "NEW"
            and surface_map["action_mutation"].get("dispatch", {}).get(
                "dispatch_status"
            )
            == "DISPATCHING"
        ),
        "sensitive_create_payload_rejected": _sensitive_create_payload_rejected(
            escalation_store,
            dispatch_store,
            escalation_id,
        ),
        "sensitive_action_payload_rejected": _sensitive_action_payload_rejected(
            escalation_store,
            dispatch_store,
            dispatch_id,
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_dispatch_privacy_regression_failed",
        "slice": SLICE_ID,
        "service": SERVICE_ID,
        "surface_count": len(surfaces),
        "surfaces": [
            {
                "name": item["name"],
                "status_code": item["status_code"],
                "payload_bytes": item["payload_bytes"],
                "leak_labels": item["leak_labels"],
            }
            for item in surface_checks
        ],
        "checks": checks,
        "fixture": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": TARGET_ID,
            "forbidden_value_labels": sorted(FORBIDDEN_VALUES),
            "covered_surfaces": [surface.name for surface in surfaces],
        },
    }
    assert_privacy_evidence_redacted(json.dumps(evidence, default=str))
    return evidence


def _build_fixture_stores() -> tuple[
    OperatorReviewCaseStore,
    OperatorReviewEscalationStore,
    OperatorReviewEscalationDispatchStore,
    InMemoryOperationalEventStore,
    str,
]:
    case_store = OperatorReviewCaseStore()
    escalation_store = OperatorReviewEscalationStore()
    dispatch_store = OperatorReviewEscalationDispatchStore()
    event_store = InMemoryOperationalEventStore()
    record = build_operator_review_escalation_record(
        _escalation_candidate(),
        {
            "operator_ref": _operator_ref(),
            "action_comment": "Safe escalation setup comment.",
            "metadata": {"source_view": "operator_review_dispatch_privacy"},
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=ESCALATION_IDEMPOTENCY_KEY,
        created_at=REFERENCE_TIME,
    )
    escalation_store.save(record)
    return case_store, escalation_store, dispatch_store, event_store, record[
        "escalation_id"
    ]


def _build_client(
    case_store: OperatorReviewCaseStore,
    escalation_store: OperatorReviewEscalationStore,
    dispatch_store: OperatorReviewEscalationDispatchStore,
    event_store: InMemoryOperationalEventStore,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_operator_review_case_routes(
        app,
        store=case_store,
        escalation_store=escalation_store,
        dispatch_store=dispatch_store,
        audit_event_store=event_store,
    )
    register_unified_operation_routes(
        app,
        event_store=event_store,
        operator_review_case_store=case_store,
        operator_review_escalation_store=escalation_store,
        operator_review_escalation_dispatch_store=dispatch_store,
    )
    return TestClient(app)


def _create_dispatch_surface(client: TestClient, escalation_id: str) -> SurfacePayload:
    response = client.post(
        f"/admin/v1/operator-review/escalations/{escalation_id}/dispatches",
        headers={**_admin_headers(), "Idempotency-Key": DISPATCH_IDEMPOTENCY_KEY},
        json={
            "dispatch_intent": "NOTIFY_OWNER",
            "channel_type": "MOCK",
            "operator_ref": _operator_ref(),
            "safe_subject": SAFE_SUBJECT,
            "safe_body": SAFE_BODY,
            "provider_payload_fingerprint": "safe-provider-payload-fingerprint-0709",
            "metadata": {"source_view": "dispatch_privacy_regression"},
        },
    )
    return SurfacePayload(
        name="dispatch_plan",
        status_code=response.status_code,
        payload=response.json(),
    )


def _collect_dispatch_read_surfaces(
    client: TestClient,
    dispatch_id: str,
) -> list[SurfacePayload]:
    query = (
        f"target_service={TARGET_SERVICE}&target_kind={TARGET_KIND}"
        f"&target_id={TARGET_ID}"
    )
    return [
        _get_payload(
            client,
            "dispatch_list",
            f"/admin/v1/operator-review/dispatches?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "dispatch_detail",
            f"/admin/v1/operator-review/dispatches/{dispatch_id}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "dashboard",
            f"/admin/v1/operations/dashboard?service_id={TARGET_SERVICE}"
            "&recent_limit=5",
            _service_headers(),
        ),
        _get_payload(
            client,
            "issue_candidates",
            f"/admin/v1/operations/issue-candidates?service_id={TARGET_SERVICE}"
            "&recent_limit=5",
            _service_headers(),
        ),
    ]


def _apply_dispatch_action_surface(
    client: TestClient,
    dispatch_id: str,
) -> SurfacePayload:
    response = client.post(
        f"/admin/v1/operator-review/dispatches/{dispatch_id}/actions",
        headers={**_admin_headers(), "Idempotency-Key": ACTION_IDEMPOTENCY_KEY},
        json={
            "action_type": "START",
            "operator_ref": {"operator_type": "service", "operator_id": "nex-ag"},
            "reason_codes": ["privacy_regression_dispatch_started"],
            "action_comment": SAFE_ACTION_COMMENT,
            "metadata": {"source_view": "dispatch_privacy_action"},
        },
    )
    return SurfacePayload(
        name="action_mutation",
        status_code=response.status_code,
        payload=response.json(),
    )


def _get_payload(
    client: TestClient,
    name: str,
    path: str,
    headers: Mapping[str, str],
) -> SurfacePayload:
    response = client.get(path, headers=dict(headers))
    return SurfacePayload(name=name, status_code=response.status_code, payload=response.json())


def _created_dispatch_id(payload: Mapping[str, Any]) -> str:
    dispatch = payload.get("dispatch_record")
    if not isinstance(dispatch, Mapping):
        return ""
    return str(dispatch.get("dispatch_id") or "")


def _sensitive_create_payload_rejected(
    escalation_store: OperatorReviewEscalationStore,
    dispatch_store: OperatorReviewEscalationDispatchStore,
    escalation_id: str,
) -> bool:
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=escalation_store,
        dispatch_store=dispatch_store,
    )
    try:
        service.create_escalation_dispatch(
            escalation_id,
            {
                "dispatch_intent": "NOTIFY_OWNER",
                "operator_ref": _operator_ref(),
                "raw_provider_payload": {"body": RAW_PROVIDER_PAYLOAD},
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0709-sensitive-create-reject",
        )
    except OperatorReviewNoteError as exc:
        return exc.error_code == "ag.operator_review_note_sensitive_payload"
    return False


def _sensitive_action_payload_rejected(
    escalation_store: OperatorReviewEscalationStore,
    dispatch_store: OperatorReviewEscalationDispatchStore,
    dispatch_id: str,
) -> bool:
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=escalation_store,
        dispatch_store=dispatch_store,
    )
    try:
        service.apply_escalation_dispatch_action(
            dispatch_id,
            {
                "action_type": "START",
                "operator_ref": {"operator_type": "service", "operator_id": "nex-ag"},
                "provider_api_key": PROVIDER_API_KEY,
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0709-sensitive-action-reject",
        )
    except OperatorReviewNoteError as exc:
        return exc.error_code == "ag.operator_review_note_sensitive_payload"
    return False


def _escalation_candidate() -> dict[str, Any]:
    return {
        "candidate_id": f"{CASE_ID}:dispatch:blocked",
        "case_id": CASE_ID,
        "target_ref": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": TARGET_ID,
        },
        "assignment_ref": {
            "assignee_type": None,
            "assignee_id": None,
            "tenant_id": "privacy-tenant",
        },
        "escalation_level": "FOLLOW_UP",
        "sla_state": "WARNING",
        "escalation_reasons": [
            "privacy_regression_dispatch_required",
            "operator_owner_notification_required",
        ],
        "runbook_ids": ["ag.operator_review_escalation_dispatch.privacy_regression.v1"],
        "recommended_operator_actions": [
            "start_or_cancel_operator_review_escalation_dispatch"
        ],
    }


def _admin_headers() -> dict[str, str]:
    issued = issue_mock_user_token(
        tenant_id="privacy-tenant",
        user_id="privacy-admin",
        audience=SERVICE_ID,
        roles=["admin"],
    )
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _service_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience=SERVICE_ID)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _operator_ref() -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": "privacy-operator",
        "tenant_id": "privacy-tenant",
    }


def _surface_privacy_check(surface: SurfacePayload) -> dict[str, Any]:
    serialized = json.dumps(surface.payload, ensure_ascii=False, sort_keys=True)
    return {
        "name": surface.name,
        "status_code": surface.status_code,
        "payload_bytes": len(serialized.encode("utf-8")),
        "leak_labels": _leak_labels(serialized, FORBIDDEN_VALUES),
    }


def _leak_labels(serialized: str, forbidden_values: Mapping[str, str]) -> list[str]:
    return [
        label
        for label, forbidden in forbidden_values.items()
        if forbidden and forbidden in serialized
    ]


def _contains_forbidden_keys(value: Any, forbidden_keys: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in forbidden_keys or _contains_forbidden_keys(child, forbidden_keys)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_keys(item, forbidden_keys) for item in value)
    return False


def _redaction_flags_safe(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in SENSITIVE_REDACTION_FLAGS and child is not False:
                return False
            if not _redaction_flags_safe(child):
                return False
    if isinstance(value, list):
        return all(_redaction_flags_safe(item) for item in value)
    return True


def _dashboard_dispatch_summary_safe(payload: Mapping[str, Any]) -> bool:
    section = payload.get("operator_review_escalation_dispatches")
    if not isinstance(section, Mapping):
        return False
    summary = section.get("summary")
    return (
        isinstance(summary, Mapping)
        and summary.get("dispatch_count") == 1
        and summary.get("attention_count") == 1
        and not _contains_forbidden_keys(section, FORBIDDEN_KEYS)
        and _redaction_flags_safe(section)
    )


def _issue_candidate_surface_safe(payload: Mapping[str, Any]) -> bool:
    candidates = payload.get("issue_candidates")
    if not isinstance(candidates, list):
        return False
    dispatch_candidates = [
        item
        for item in candidates
        if isinstance(item, Mapping)
        and item.get("rule_id")
        == "operator_review_escalation_dispatch_attention_required.v1"
    ]
    if len(dispatch_candidates) != 1:
        return False
    candidate = dispatch_candidates[0]
    return (
        candidate.get("service_id") == SERVICE_ID
        and candidate.get("signal", {}).get("count") == 1
        and not _contains_forbidden_keys(candidate, FORBIDDEN_KEYS)
        and _redaction_flags_safe(candidate)
    )


def assert_privacy_evidence_redacted(serialized_evidence: str) -> None:
    leaks = _leak_labels(serialized_evidence, FORBIDDEN_VALUES)
    if leaks:
        raise ValueError(
            "AG operator review escalation dispatch privacy evidence leaked labels: "
            f"{', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_escalation_dispatch_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_escalation_dispatch_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review escalation dispatch privacy regression."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_dispatch_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
