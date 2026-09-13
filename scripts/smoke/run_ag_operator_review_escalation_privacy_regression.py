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


SCHEMA_VERSION = "ag_operator_review_escalation_privacy_regression.v1"
SLICE_ID = "0698"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_escalation_privacy"
TARGET_ID = "operator-review-escalation-privacy-0698"
CASE_ID = "case-operator-review-escalation-privacy-0698"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
REFERENCE_TIME = "2026-09-12T12:00:00Z"

RAW_ACTION_COMMENT = "RAW_ACTION_SECRET_0698_SHOULD_NOT_LEAK"
RAW_NOTIFICATION_PAYLOAD = "RAW_NOTIFICATION_PAYLOAD_0698_SHOULD_NOT_LEAK"
RAW_EXTERNAL_INCIDENT_PAYLOAD = "RAW_EXTERNAL_INCIDENT_0698_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0698_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0698_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/escalation-0698.pdf"
IDEMPOTENCY_KEY = "idem-0698-create-secret"
ACTION_IDEMPOTENCY_KEY = "idem-0698-action-secret"
PROVIDER_API_KEY = "provider-key-0698"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0698"
SAFE_COMMENT = "Escalation acknowledged for privacy regression."

FORBIDDEN_VALUES = {
    "raw_action_comment": RAW_ACTION_COMMENT,
    "raw_notification_payload": RAW_NOTIFICATION_PAYLOAD,
    "raw_external_incident_payload": RAW_EXTERNAL_INCIDENT_PAYLOAD,
    "raw_prompt": RAW_PROMPT,
    "raw_source_text": RAW_SOURCE_TEXT,
    "storage_path": STORAGE_PATH,
    "idempotency_key": IDEMPOTENCY_KEY,
    "action_idempotency_key": ACTION_IDEMPOTENCY_KEY,
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
    "raw_action_comment",
    "raw_external_incident_payload",
    "raw_notification_payload",
    "raw_prompt",
    "raw_source_text",
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
    "raw_action_comment_included",
    "raw_external_incident_payload_included",
    "raw_notification_payload_included",
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


def run_ag_operator_review_escalation_privacy_regression() -> dict[str, Any]:
    case_store, escalation_store, event_store, escalation_id = _build_fixture_stores()
    client = _build_client(case_store, escalation_store, event_store)
    pre_action_surfaces = _collect_pre_action_surface_payloads(client, escalation_id)
    action_surface = _apply_action_surface(client, escalation_id)
    surfaces = [*pre_action_surfaces, action_surface]
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
        "list_surface_ready": (
            surface_map["escalation_list"].get("escalation_list_schema_version")
            == "ag_operator_review_escalation_list.v1"
            and surface_map["escalation_list"].get("summary", {}).get("count") == 1
        ),
        "detail_surface_ready": (
            surface_map["escalation_detail"].get("escalation_schema_version")
            == "ag_operator_review_escalation.v1"
            and surface_map["escalation_detail"].get("escalation_status") == "ACTIVE"
        ),
        "dashboard_surface_ready": _dashboard_escalation_summary_safe(
            surface_map["dashboard"]
        ),
        "issue_candidate_surface_ready": _issue_candidate_surface_safe(
            surface_map["issue_candidates"]
        ),
        "action_surface_ready": (
            surface_map["action_mutation"].get(
                "escalation_action_mutation_schema_version"
            )
            == "ag_operator_review_escalation_action_mutation.v1"
            and surface_map["action_mutation"].get("idempotency_status") == "NEW"
            and surface_map["action_mutation"]
            .get("escalation", {})
            .get("escalation_status")
            == "ACKNOWLEDGED"
        ),
        "sensitive_action_payload_rejected": _sensitive_action_payload_rejected(
            escalation_store,
            escalation_id,
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_escalation_privacy_regression_failed",
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
    InMemoryOperationalEventStore,
    str,
]:
    case_store = OperatorReviewCaseStore()
    escalation_store = OperatorReviewEscalationStore()
    event_store = InMemoryOperationalEventStore()
    record = build_operator_review_escalation_record(
        _escalation_candidate(),
        {
            "operator_ref": _operator_ref(),
            "action_comment": SAFE_COMMENT,
            "metadata": {"source_view": "operator_review_escalation_privacy"},
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        created_at=REFERENCE_TIME,
    )
    escalation_store.save(record)
    return case_store, escalation_store, event_store, record["escalation_id"]


def _build_client(
    case_store: OperatorReviewCaseStore,
    escalation_store: OperatorReviewEscalationStore,
    event_store: InMemoryOperationalEventStore,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_operator_review_case_routes(
        app,
        store=case_store,
        escalation_store=escalation_store,
        audit_event_store=event_store,
    )
    register_unified_operation_routes(
        app,
        event_store=event_store,
        operator_review_case_store=case_store,
        operator_review_escalation_store=escalation_store,
    )
    return TestClient(app)


def _collect_pre_action_surface_payloads(
    client: TestClient,
    escalation_id: str,
) -> list[SurfacePayload]:
    query = (
        f"target_service={TARGET_SERVICE}&target_kind={TARGET_KIND}"
        f"&target_id={TARGET_ID}"
    )
    return [
        _get_payload(
            client,
            "escalation_list",
            f"/admin/v1/operator-review/escalations?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "escalation_detail",
            f"/admin/v1/operator-review/escalations/{escalation_id}",
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


def _apply_action_surface(client: TestClient, escalation_id: str) -> SurfacePayload:
    response = client.post(
        f"/admin/v1/operator-review/escalations/{escalation_id}/actions",
        headers={
            **_admin_headers(),
            "Idempotency-Key": ACTION_IDEMPOTENCY_KEY,
        },
        json={
            "action_type": "ACKNOWLEDGE",
            "operator_ref": _operator_ref(),
            "reason_codes": ["privacy_regression_acknowledged"],
            "action_comment": SAFE_COMMENT,
            "metadata": {"source_view": "privacy_regression_action"},
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


def _sensitive_action_payload_rejected(
    escalation_store: OperatorReviewEscalationStore,
    escalation_id: str,
) -> bool:
    service = OperatorReviewCaseService(
        OperatorReviewCaseStore(),
        escalation_store=escalation_store,
    )
    try:
        service.apply_escalation_action(
            escalation_id,
            {
                "action_type": "ACKNOWLEDGE",
                "operator_ref": _operator_ref(),
                "raw_prompt": RAW_PROMPT,
            },
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
            idempotency_key="idem-0698-sensitive-reject",
        )
    except OperatorReviewNoteError as exc:
        return exc.error_code == "ag.operator_review_note_sensitive_payload"
    return False


def _escalation_candidate() -> dict[str, Any]:
    return {
        "candidate_id": f"{CASE_ID}:overdue:blocked",
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
        "escalation_level": "BLOCKED",
        "sla_state": "OVERDUE",
        "escalation_reasons": [
            "privacy_regression_active_escalation",
            "operator_action_required",
        ],
        "runbook_ids": ["ag.operator_review_escalation.privacy_regression.v1"],
        "recommended_operator_actions": [
            "acknowledge_or_resolve_operator_review_escalation"
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


def _dashboard_escalation_summary_safe(payload: Mapping[str, Any]) -> bool:
    section = payload.get("operator_review_escalations")
    if not isinstance(section, Mapping):
        return False
    return (
        section.get("summary", {}).get("escalation_count") == 1
        and section.get("summary", {}).get("action_required_count") == 1
        and not _contains_forbidden_keys(section, FORBIDDEN_KEYS)
        and _redaction_flags_safe(section)
    )


def _issue_candidate_surface_safe(payload: Mapping[str, Any]) -> bool:
    candidates = payload.get("issue_candidates")
    if not isinstance(candidates, list):
        return False
    escalation_candidates = [
        item
        for item in candidates
        if isinstance(item, Mapping)
        and item.get("rule_id") == "operator_review_escalation_action_required.v1"
    ]
    if len(escalation_candidates) != 1:
        return False
    candidate = escalation_candidates[0]
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
            "AG operator review escalation privacy evidence leaked labels: "
            f"{', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_escalation_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_escalation_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review escalation privacy regression."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_escalation_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
