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
    OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
    OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    register_operator_review_case_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_operational_event,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ag_operator_review_case_workbench_privacy_regression.v1"
SLICE_ID = "0659"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-cx"
TARGET_KIND = "operator_review_case_privacy"
TARGET_ID = "operator-review-case-privacy-0659"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"

RAW_ACTION_SENTINEL = "RAW_ACTION_SECRET_0659_SHOULD_NOT_LEAK"
RAW_ACTION_COMMENT = (
    "Operator review case action preview budget filler. " * 7
    + RAW_ACTION_SENTINEL
)
RAW_RESOLUTION_COMMENT = "RAW_RESOLUTION_SECRET_0659_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0659_SHOULD_NOT_LEAK"
RAW_GENERATION_OUTPUT = "RAW_GENERATION_OUTPUT_SECRET_0659_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0659_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/case-workbench-0659.pdf"
IDEMPOTENCY_KEY = "idem-0659-secret-key"
PROVIDER_API_KEY = "provider-key-0659"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0659"

FORBIDDEN_VALUES = {
    "raw_action_comment_full_text": RAW_ACTION_COMMENT,
    "raw_action_comment_sentinel": RAW_ACTION_SENTINEL,
    "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
    "raw_prompt": RAW_PROMPT,
    "raw_generation_output": RAW_GENERATION_OUTPUT,
    "raw_source_text": RAW_SOURCE_TEXT,
    "storage_path": STORAGE_PATH,
    "idempotency_key": IDEMPOTENCY_KEY,
    "provider_api_key": PROVIDER_API_KEY,
    "database_url": DATABASE_URL,
    "service_token": SERVICE_TOKEN,
}

FORBIDDEN_KEYS = {
    "action_comment",
    "database_url",
    "idempotency_key",
    "provider_api_key",
    "raw_action_comment",
    "raw_generation_output",
    "raw_prompt",
    "raw_resolution_comment",
    "raw_source_text",
    "resolution_comment",
    "service_token",
    "storage_path",
    "storage_uri",
}

CASE_REDACTION_FLAGS = (
    "raw_case_comment_included",
    "raw_action_comment_included",
    "raw_resolution_comment_included",
    "raw_prompt_included",
    "raw_generation_output_included",
    "raw_source_text_included",
    "storage_paths_included",
    "idempotency_keys_included",
)


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_case_workbench_privacy_regression() -> dict[str, Any]:
    case_store, event_store, case_id = _build_fixture_stores()
    surfaces = _collect_surface_payloads(case_store, event_store, case_id=case_id)
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    surface_map = {surface.name: surface.payload for surface in surfaces}
    checks = {
        "all_routes_200": all(surface.status_code == 200 for surface in surfaces),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "raw_fields_absent": all(
            not _contains_forbidden_keys(surface.payload, FORBIDDEN_KEYS)
            for surface in surfaces
        ),
        "queue_action_material_safe": _action_material_safe(surface_map["queue"]),
        "detail_action_material_safe": _action_material_safe(
            surface_map["workbench_detail"]
        ),
        "timeline_metadata_only": _timeline_metadata_only(surface_map["timeline"]),
        "queue_redaction_flags_safe": _redaction_flags_safe(surface_map["queue"]),
        "detail_redaction_flags_safe": _redaction_flags_safe(
            surface_map["workbench_detail"]
        ),
        "timeline_redaction_flags_safe": _redaction_flags_safe(
            surface_map["timeline"]
        ),
        "dashboard_case_section_safe": _dashboard_case_section_safe(
            surface_map["dashboard"]
        ),
        "issue_candidates_reference_safe_cases": _issue_candidates_safe(
            surface_map["issue_candidates"]
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_case_workbench_privacy_regression_failed",
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
            "case_id": case_id,
            "preview_limit": 240,
            "raw_action_length": len(RAW_ACTION_COMMENT),
            "forbidden_value_labels": sorted(FORBIDDEN_VALUES),
            "covered_surfaces": [surface.name for surface in surfaces],
        },
    }
    assert_privacy_evidence_redacted(json.dumps(evidence, default=str))
    return evidence


def _build_fixture_stores() -> tuple[
    OperatorReviewCaseStore,
    InMemoryOperationalEventStore,
    str,
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
    case_id = str(mutation["case"]["case_id"])
    action_mutation = service.apply_action(
        case_id,
        _action_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=f"{IDEMPOTENCY_KEY}-action",
    )
    unsafe_case = _unsafe_case_record(action_mutation["case"])
    case_store.save(unsafe_case)
    event_store.append(_unsafe_case_event(unsafe_case))
    event_store.append(_unsafe_action_event(action_mutation["action"], unsafe_case))
    return case_store, event_store, case_id


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
        "reason_codes": ["privacy_regression", "operator_review_case_workbench"],
        "metadata": {"source_view": "operator_review_case_workbench"},
    }


def _action_payload() -> dict[str, Any]:
    return {
        "action_type": "ASSIGN",
        "operator_ref": _operator_ref(),
        "assignment_ref": {
            "assignee_type": "user",
            "assignee_id": "privacy-assignee",
            "tenant_id": "privacy-tenant",
        },
        "reason_codes": ["privacy_regression"],
        "action_comment": RAW_ACTION_COMMENT,
        "metadata": {"source_view": "operator_review_case_workbench"},
    }


def _unsafe_case_record(record: dict[str, Any]) -> dict[str, Any]:
    unsafe = json.loads(json.dumps(record))
    unsafe.update(
        {
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
    unsafe["assignment_ref"] = {
        **dict(unsafe.get("assignment_ref") or {}),
        "service_token": SERVICE_TOKEN,
    }
    metadata = dict(unsafe.get("metadata") or {})
    last_action = dict(metadata.get("last_action") or {})
    last_action_record = dict(last_action.get("record") or {})
    last_action_record.update(
        {
            "raw_action_comment": RAW_ACTION_COMMENT,
            "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
            "raw_prompt": RAW_PROMPT,
            "storage_path": STORAGE_PATH,
            "provider_api_key": PROVIDER_API_KEY,
        }
    )
    last_action["record"] = last_action_record
    metadata.update(
        {
            "last_action": last_action,
            "idempotency_key": IDEMPOTENCY_KEY,
            "database_url": DATABASE_URL,
            "service_token": SERVICE_TOKEN,
            "raw_prompt": RAW_PROMPT,
            "raw_generation_output": RAW_GENERATION_OUTPUT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "storage_path": STORAGE_PATH,
        }
    )
    unsafe["metadata"] = metadata
    return unsafe


def _unsafe_case_event(record: dict[str, Any]) -> dict[str, Any]:
    return build_operational_event(
        service_id=SERVICE_ID,
        event_type=OPERATOR_REVIEW_CASE_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="AG operator review case privacy regression recorded.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref={"type": "operator_review_case", "id": str(record["case_id"])},
        details={
            "case_id": record["case_id"],
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": TARGET_ID,
            "case_status": record["case_status"],
            "case_priority": record["case_priority"],
            "action_comment": RAW_ACTION_COMMENT,
            "raw_prompt": RAW_PROMPT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "storage_path": STORAGE_PATH,
            "idempotency_key": IDEMPOTENCY_KEY,
        },
        created_at="2026-09-10T00:00:00Z",
        event_id="ag-case-workbench-privacy-case-0659",
    )


def _unsafe_action_event(
    action: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    return build_operational_event(
        service_id=SERVICE_ID,
        event_type=OPERATOR_REVIEW_CASE_ACTION_RECORDED_EVENT_TYPE,
        severity="INFO",
        message="AG operator review case action privacy regression recorded.",
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
        subject_ref={
            "type": "operator_review_case_action",
            "id": str(action["action_id"]),
        },
        details={
            "case_id": record["case_id"],
            "action_id": action["action_id"],
            "action_type": action["action_type"],
            "from_status": action["from_status"],
            "to_status": action["to_status"],
            "case_status": record["case_status"],
            "target_service": TARGET_SERVICE,
            "target_kind": TARGET_KIND,
            "target_id": TARGET_ID,
            "operator_type": "user",
            "operator_id": "privacy-operator",
            "assignee_id": "privacy-assignee",
            "action_comment_hash": action.get("action_comment_hash"),
            "action_comment": RAW_ACTION_COMMENT,
            "resolution_comment": RAW_RESOLUTION_COMMENT,
            "raw_generation_output": RAW_GENERATION_OUTPUT,
            "provider_api_key": PROVIDER_API_KEY,
            "service_token": SERVICE_TOKEN,
        },
        created_at="2026-09-10T00:01:00Z",
        event_id="ag-case-workbench-privacy-action-0659",
    )


def _collect_surface_payloads(
    case_store: OperatorReviewCaseStore,
    event_store: InMemoryOperationalEventStore,
    *,
    case_id: str,
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
        f"&target_id={TARGET_ID}&latest_action_type=ASSIGN"
    )
    return [
        _get_payload(
            client,
            "queue",
            f"/admin/v1/operator-review/cases/queue?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "workbench_detail",
            f"/admin/v1/operator-review/cases/{case_id}/workbench-detail",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "timeline",
            f"/admin/v1/operator-review/cases/{case_id}/timeline?limit=10",
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


def _previews_are_bounded(payload: Mapping[str, Any]) -> bool:
    previews = _collect_preview_values(payload)
    return all(
        isinstance(preview, str)
        and len(preview) <= 240
        and RAW_ACTION_SENTINEL not in preview
        and RAW_RESOLUTION_COMMENT not in preview
        for preview in previews
    )


def _collect_preview_values(value: Any) -> list[str]:
    previews: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str) and key.endswith("_preview") and child is not None:
                previews.append(str(child))
            previews.extend(_collect_preview_values(child))
    elif isinstance(value, list):
        for item in value:
            previews.extend(_collect_preview_values(item))
    return previews


def _action_material_safe(payload: Mapping[str, Any]) -> bool:
    hashes = _collect_hash_values(payload)
    return (
        bool(hashes)
        and all(_is_sha256_hex(value) for value in hashes)
        and _previews_are_bounded(payload)
    )


def _collect_hash_values(value: Any) -> list[str]:
    hashes: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if (
                key in {"action_comment_hash", "resolution_hash"}
                and isinstance(child, str)
            ):
                hashes.append(child)
            hashes.extend(_collect_hash_values(child))
    elif isinstance(value, list):
        for item in value:
            hashes.extend(_collect_hash_values(item))
    return hashes


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _timeline_metadata_only(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return False
    return (
        summary.get("timeline_status") == "READY"
        and summary.get("case_recorded_event_count") == 1
        and summary.get("case_action_event_count") == 1
        and not _contains_forbidden_keys(payload, FORBIDDEN_KEYS)
    )


def _redaction_flags_safe(payload: Mapping[str, Any]) -> bool:
    redaction = payload.get("redaction")
    if not isinstance(redaction, Mapping):
        return False
    return all(redaction.get(key) is False for key in CASE_REDACTION_FLAGS)


def _dashboard_case_section_safe(payload: Mapping[str, Any]) -> bool:
    section = payload.get("operator_review_cases")
    if not isinstance(section, Mapping):
        return False
    summary = section.get("summary")
    attention = section.get("attention")
    return (
        isinstance(summary, Mapping)
        and summary.get("case_count") == 1
        and isinstance(attention, list)
        and bool(attention)
        and _redaction_flags_safe(section)
        and not _contains_forbidden_keys(section, FORBIDDEN_KEYS)
    )


def _issue_candidates_safe(payload: Mapping[str, Any]) -> bool:
    candidates = payload.get("issue_candidates")
    if not isinstance(candidates, list):
        return False
    return any(
        isinstance(candidate, Mapping)
        and candidate.get("rule_id") == "operator_review_case_attention_required.v1"
        and isinstance(candidate.get("signal"), Mapping)
        and candidate["signal"].get("source_type") == "operator_review_case"
        and not _contains_forbidden_keys(candidate, FORBIDDEN_KEYS)
        for candidate in candidates
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
            "AG operator review case workbench privacy evidence leaked labels: "
            f"{', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_case_workbench_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_case_workbench_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review case workbench privacy regression audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_case_workbench_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
