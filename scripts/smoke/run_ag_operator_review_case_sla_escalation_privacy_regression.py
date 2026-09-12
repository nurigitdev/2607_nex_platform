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
    register_operator_review_case_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ag_operator_review_case_sla_escalation_privacy_regression.v1"
SLICE_ID = "0688"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_case_sla_privacy"
TARGET_ID = "operator-review-case-sla-privacy-0688"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
REFERENCE_TIME = "2026-09-12T12:00:00Z"

RAW_CASE_COMMENT = "RAW_CASE_SECRET_0688_SHOULD_NOT_LEAK"
RAW_ACTION_COMMENT = "RAW_ACTION_SECRET_0688_SHOULD_NOT_LEAK"
RAW_RESOLUTION_COMMENT = "RAW_RESOLUTION_SECRET_0688_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0688_SHOULD_NOT_LEAK"
RAW_GENERATION_OUTPUT = "RAW_GENERATION_OUTPUT_SECRET_0688_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0688_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/sla-escalation-0688.pdf"
IDEMPOTENCY_KEY = "idem-0688-secret-key"
PROVIDER_API_KEY = "provider-key-0688"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0688"
NOTIFICATION_PAYLOAD = "notification-payload-0688-should-not-leak"
EXTERNAL_INCIDENT_PAYLOAD = "external-incident-payload-0688-should-not-leak"

FORBIDDEN_VALUES = {
    "raw_case_comment": RAW_CASE_COMMENT,
    "raw_action_comment": RAW_ACTION_COMMENT,
    "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
    "raw_prompt": RAW_PROMPT,
    "raw_generation_output": RAW_GENERATION_OUTPUT,
    "raw_source_text": RAW_SOURCE_TEXT,
    "storage_path": STORAGE_PATH,
    "idempotency_key": IDEMPOTENCY_KEY,
    "provider_api_key": PROVIDER_API_KEY,
    "database_url": DATABASE_URL,
    "service_token": SERVICE_TOKEN,
    "notification_payload": NOTIFICATION_PAYLOAD,
    "external_incident_payload": EXTERNAL_INCIDENT_PAYLOAD,
}

FORBIDDEN_KEYS = {
    "action_comment",
    "database_url",
    "external_incident_payload",
    "idempotency_key",
    "notification_payload",
    "provider_api_key",
    "raw_action_comment",
    "raw_case_comment",
    "raw_generation_output",
    "raw_prompt",
    "raw_resolution_comment",
    "raw_source_text",
    "resolution_comment",
    "service_token",
    "storage_path",
    "storage_uri",
}

SENSITIVE_REDACTION_FLAGS = {
    "database_urls_included",
    "external_incident_payload_included",
    "idempotency_keys_included",
    "metadata_payload_included",
    "notification_payload_included",
    "provider_payloads_included",
    "raw_action_comment_included",
    "raw_case_comment_included",
    "raw_generation_output_included",
    "raw_prompt_included",
    "raw_resolution_comment_included",
    "raw_source_text_included",
    "storage_paths_included",
    "tokens_included",
}


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_case_sla_escalation_privacy_regression() -> dict[str, Any]:
    case_store, event_store = _build_fixture_stores()
    surfaces = _collect_surface_payloads(case_store, event_store)
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    surface_map = {surface.name: surface.payload for surface in surfaces}
    checks = {
        "all_routes_200": all(surface.status_code == 200 for surface in surfaces),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "raw_fields_absent": all(
            not _contains_forbidden_keys(surface.payload, FORBIDDEN_KEYS)
            for surface in surfaces
        ),
        "redaction_flags_safe": all(
            _redaction_flags_safe(surface.payload) for surface in surfaces
        ),
        "sla_policy_surface_ready": (
            surface_map["sla_policy"].get("case_sla_policy_schema_version")
            == "ag_operator_review_case_sla_policy.v1"
        ),
        "aging_surface_ready": (
            surface_map["aging"].get("case_aging_schema_version")
            == "ag_operator_review_case_aging.v1"
            and surface_map["aging"].get("summary", {}).get("overdue_case_count") == 1
        ),
        "escalation_surface_ready": (
            surface_map["escalations"].get("case_escalations_schema_version")
            == "ag_operator_review_case_escalations.v1"
            and surface_map["escalations"].get("summary", {}).get("candidate_count")
            == 1
        ),
        "dashboard_sla_summary_safe": _dashboard_sla_summary_safe(
            surface_map["dashboard"]
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_case_sla_escalation_privacy_regression_failed",
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
    InMemoryOperationalEventStore,
]:
    case_store = OperatorReviewCaseStore()
    event_store = InMemoryOperationalEventStore()
    service = OperatorReviewCaseService(case_store)
    mutation = service.create_case(
        _case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    case_store.save(_unsafe_case_record(mutation["case"]))
    return case_store, event_store


def _case_payload() -> dict[str, Any]:
    return {
        "target_ref": {
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": TARGET_ID,
        },
        "operator_ref": _operator_ref(),
        "case_status": "OPEN",
        "case_priority": "URGENT",
        "source_ref": {
            "source_type": "operator_review_workbench",
            "source_id": TARGET_ID,
            "source_service": SERVICE_ID,
            "workbench_path": "/admin/v1/operator-review/workbench",
        },
        "assignment_ref": None,
        "reason_codes": ["privacy_regression", "sla_escalation"],
        "metadata": {"source_view": "operator_review_case_sla_escalation"},
    }


def _unsafe_case_record(record: dict[str, Any]) -> dict[str, Any]:
    unsafe = json.loads(json.dumps(record))
    unsafe.update(
        {
            "raw_case_comment": RAW_CASE_COMMENT,
            "raw_action_comment": RAW_ACTION_COMMENT,
            "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
            "raw_prompt": RAW_PROMPT,
            "raw_generation_output": RAW_GENERATION_OUTPUT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "storage_path": STORAGE_PATH,
            "provider_api_key": PROVIDER_API_KEY,
        }
    )
    unsafe["source_ref"] = {
        **dict(unsafe.get("source_ref") or {}),
        "raw_source_text": RAW_SOURCE_TEXT,
        "storage_path": STORAGE_PATH,
    }
    metadata = dict(unsafe.get("metadata") or {})
    metadata.update(
        {
            "action_comment": RAW_ACTION_COMMENT,
            "database_url": DATABASE_URL,
            "external_incident_payload": EXTERNAL_INCIDENT_PAYLOAD,
            "idempotency_key": IDEMPOTENCY_KEY,
            "notification_payload": NOTIFICATION_PAYLOAD,
            "raw_prompt": RAW_PROMPT,
            "raw_generation_output": RAW_GENERATION_OUTPUT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "service_token": SERVICE_TOKEN,
            "storage_path": STORAGE_PATH,
        }
    )
    unsafe["metadata"] = metadata
    return unsafe


def _collect_surface_payloads(
    case_store: OperatorReviewCaseStore,
    event_store: InMemoryOperationalEventStore,
) -> list[SurfacePayload]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_operator_review_case_routes(
        app,
        store=case_store,
        audit_event_store=event_store,
    )
    register_unified_operation_routes(
        app,
        event_store=event_store,
        operator_review_case_store=case_store,
    )
    client = TestClient(app)
    query = (
        f"target_service={TARGET_SERVICE}&target_kind={TARGET_KIND}"
        f"&target_id={TARGET_ID}&now={REFERENCE_TIME}"
    )
    return [
        _get_payload(
            client,
            "sla_policy",
            "/admin/v1/operator-review/cases/sla-policy",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "aging",
            f"/admin/v1/operator-review/cases/aging?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "escalations",
            f"/admin/v1/operator-review/cases/escalations?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "dashboard",
            f"/admin/v1/operations/dashboard?service_id={TARGET_SERVICE}"
            "&recent_limit=5",
            _service_headers(),
        ),
    ]


def _get_payload(
    client: TestClient,
    name: str,
    path: str,
    headers: Mapping[str, str],
) -> SurfacePayload:
    response = client.get(path, headers=dict(headers))
    return SurfacePayload(name=name, status_code=response.status_code, payload=response.json())


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


def _dashboard_sla_summary_safe(payload: Mapping[str, Any]) -> bool:
    section = payload.get("operator_review_cases")
    if not isinstance(section, Mapping):
        return False
    escalations = section.get("escalations")
    sla_aging = section.get("sla_aging")
    return (
        isinstance(escalations, Mapping)
        and isinstance(sla_aging, Mapping)
        and escalations.get("summary", {}).get("candidate_count") == 1
        and sla_aging.get("summary", {}).get("overdue_case_count") == 1
        and not _contains_forbidden_keys(section, FORBIDDEN_KEYS)
        and _redaction_flags_safe(section)
    )


def _operator_ref() -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": "privacy-operator",
        "tenant_id": "privacy-tenant",
    }


def assert_privacy_evidence_redacted(serialized_evidence: str) -> None:
    leaks = _leak_labels(serialized_evidence, FORBIDDEN_VALUES)
    if leaks:
        raise ValueError(
            "AG operator review case SLA/escalation privacy evidence leaked labels: "
            f"{', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_case_sla_escalation_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_case_sla_escalation_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review case SLA/escalation privacy regression."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_case_sla_escalation_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
