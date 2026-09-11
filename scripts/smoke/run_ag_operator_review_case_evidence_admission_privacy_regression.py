#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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

from nex_ag.operator_review_cases import (  # noqa: E402
    OperatorReviewCaseService,
    OperatorReviewCaseStore,
    register_operator_review_case_routes,
)
from nex_ag.operator_reviews import (  # noqa: E402
    OperatorEvidenceExportStore,
    OperatorReviewNoteStore,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ag_operator_review_case_evidence_admission_privacy_regression.v1"
SLICE_ID = "0669"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-ag"
TARGET_KIND = "operator_review_workbench"
TARGET_ID = "operator-review-case-evidence-admission-privacy-0669"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"

RAW_OPERATOR_NOTE = "RAW_OPERATOR_NOTE_SECRET_0669_SHOULD_NOT_LEAK"
RAW_EVIDENCE_BODY = "RAW_EVIDENCE_BODY_SECRET_0669_SHOULD_NOT_LEAK"
RAW_ACTION_COMMENT = "RAW_ACTION_SECRET_0669_SHOULD_NOT_LEAK"
RAW_RESOLUTION_COMMENT = "RAW_RESOLUTION_SECRET_0669_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0669_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0669_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/case-evidence-admission-0669.pdf"
IDEMPOTENCY_KEY = "idem-0669-secret-key"
PROVIDER_API_KEY = "provider-key-0669"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0669"

FORBIDDEN_VALUES = {
    "raw_operator_note": RAW_OPERATOR_NOTE,
    "raw_evidence_body": RAW_EVIDENCE_BODY,
    "raw_action_comment": RAW_ACTION_COMMENT,
    "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
    "raw_prompt": RAW_PROMPT,
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
    "evidence_manifest",
    "idempotency_key",
    "metadata",
    "provider_api_key",
    "raw_action_comment",
    "raw_evidence_body",
    "raw_operator_note",
    "raw_prompt",
    "raw_resolution_comment",
    "raw_source_text",
    "resolution_comment",
    "service_token",
    "storage_path",
    "storage_uri",
}

DETAIL_REDACTION_FLAGS = (
    "raw_case_comment_included",
    "raw_action_comment_included",
    "raw_resolution_comment_included",
    "raw_prompt_included",
    "raw_generation_output_included",
    "raw_source_text_included",
    "storage_paths_included",
    "provider_payloads_included",
    "database_urls_included",
    "tokens_included",
    "idempotency_keys_included",
)

EVIDENCE_REDACTION_FLAGS = (
    "raw_operator_note_included",
    "raw_evidence_body_included",
    "storage_paths_included",
    "idempotency_keys_included",
    "provider_payloads_included",
    "database_urls_included",
    "tokens_included",
)

ADMISSION_REDACTION_FLAGS = (
    "raw_action_comment_included",
    "raw_resolution_comment_included",
    "idempotency_keys_included",
    "provider_payloads_included",
    "database_urls_included",
    "tokens_included",
)


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_case_evidence_admission_privacy_regression() -> dict[str, Any]:
    case_store, note_store, export_store, case_id = _build_fixture_stores()
    surfaces = _collect_surface_payloads(
        case_store,
        note_store,
        export_store,
        case_id=case_id,
    )
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    surface_map = {surface.name: surface.payload for surface in surfaces}
    checks = {
        "all_routes_200": all(surface.status_code == 200 for surface in surfaces),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "raw_fields_absent": all(
            not _contains_forbidden_keys(surface.payload, FORBIDDEN_KEYS)
            for surface in surfaces
        ),
        "workbench_detail_summary_only": _workbench_detail_summary_only(
            surface_map["workbench_detail"]
        ),
        "workbench_detail_redaction_safe": _redaction_flags_safe(
            surface_map["workbench_detail"],
            DETAIL_REDACTION_FLAGS,
        ),
        "evidence_links_safe": _evidence_links_safe(surface_map["evidence_links"]),
        "evidence_redaction_safe": _redaction_flags_safe(
            surface_map["evidence_links"],
            EVIDENCE_REDACTION_FLAGS,
        ),
        "evidence_item_redaction_safe": _evidence_item_redaction_safe(
            surface_map["evidence_links"]
        ),
        "action_admission_safe": _action_admission_safe(
            surface_map["action_admission"]
        ),
        "action_admission_redaction_safe": _redaction_flags_safe(
            surface_map["action_admission"],
            ADMISSION_REDACTION_FLAGS,
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_case_evidence_admission_privacy_regression_failed",
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
            "forbidden_value_labels": sorted(FORBIDDEN_VALUES),
            "covered_surfaces": [surface.name for surface in surfaces],
        },
    }
    assert_privacy_evidence_redacted(json.dumps(evidence, default=str))
    return evidence


def _build_fixture_stores() -> tuple[
    OperatorReviewCaseStore,
    OperatorReviewNoteStore,
    OperatorEvidenceExportStore,
    str,
]:
    case_store = OperatorReviewCaseStore()
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    service = OperatorReviewCaseService(case_store)
    mutation = service.create_case(
        _case_payload(),
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=IDEMPOTENCY_KEY,
    )
    case_id = str(mutation["case"]["case_id"])
    unsafe_case = _unsafe_case_record(mutation["case"])
    case_store.save(unsafe_case)
    note_store.save(_unsafe_note_record())
    export_store.save(_unsafe_export_record())
    return case_store, note_store, export_store, case_id


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
        "reason_codes": ["privacy_regression", "operator_review_case_evidence"],
        "resolution_comment": "Bounded resolution preview only.",
        "metadata": {"source_view": "operator_review_case_evidence_admission"},
    }


def _unsafe_case_record(record: dict[str, Any]) -> dict[str, Any]:
    unsafe = json.loads(json.dumps(record))
    unsafe.update(
        {
            "raw_action_comment": RAW_ACTION_COMMENT,
            "raw_resolution_comment": RAW_RESOLUTION_COMMENT,
            "raw_prompt": RAW_PROMPT,
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
            "idempotency_key": IDEMPOTENCY_KEY,
            "database_url": DATABASE_URL,
            "service_token": SERVICE_TOKEN,
            "raw_prompt": RAW_PROMPT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "storage_path": STORAGE_PATH,
        }
    )
    unsafe["metadata"] = metadata
    return unsafe


def _unsafe_note_record() -> dict[str, Any]:
    return {
        "operator_note_schema_version": "ag_operator_review_note.v1",
        "operator_note_id": "note-0669-privacy",
        "target_service": TARGET_SERVICE,
        "target_kind": TARGET_KIND,
        "target_id": TARGET_ID,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "operator_ref": _operator_ref(),
        "note_status": "ACTIVE",
        "note_type": "FOLLOW_UP",
        "severity": "HIGH",
        "operator_note_hash": _sha256_text(RAW_OPERATOR_NOTE),
        "operator_note_preview": "Bounded safe operator note preview.",
        "reason_codes": ["privacy_regression"],
        "metadata": {
            "raw_operator_note": RAW_OPERATOR_NOTE,
            "database_url": DATABASE_URL,
            "provider_api_key": PROVIDER_API_KEY,
            "storage_path": STORAGE_PATH,
        },
        "raw_operator_note": RAW_OPERATOR_NOTE,
        "created_at": "2026-09-11T00:01:00Z",
        "updated_at": "2026-09-11T00:03:00Z",
    }


def _unsafe_export_record() -> dict[str, Any]:
    return {
        "export_schema_version": "ag_redacted_evidence_export.v1",
        "export_id": "export-0669-privacy",
        "target_service": TARGET_SERVICE,
        "target_kind": TARGET_KIND,
        "target_id": TARGET_ID,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "operator_ref": _operator_ref(),
        "export_status": "READY",
        "export_format": "json",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {
            "items": [
                {
                    "evidence_type": "operator_note",
                    "raw_evidence_body": RAW_EVIDENCE_BODY,
                }
            ]
        },
        "evidence_hash": _sha256_text(RAW_EVIDENCE_BODY),
        "evidence_item_count": 1,
        "metadata": {
            "raw_evidence_body": RAW_EVIDENCE_BODY,
            "database_url": DATABASE_URL,
            "service_token": SERVICE_TOKEN,
            "storage_uri": STORAGE_PATH,
        },
        "created_at": "2026-09-11T00:02:00Z",
        "updated_at": "2026-09-11T00:02:30Z",
    }


def _collect_surface_payloads(
    case_store: OperatorReviewCaseStore,
    note_store: OperatorReviewNoteStore,
    export_store: OperatorEvidenceExportStore,
    *,
    case_id: str,
) -> list[SurfacePayload]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_operator_review_case_routes(
        app,
        store=case_store,
        note_store=note_store,
        export_store=export_store,
    )
    client = TestClient(app)
    return [
        _get_payload(
            client,
            "workbench_detail",
            f"/admin/v1/operator-review/cases/{case_id}/workbench-detail",
        ),
        _get_payload(
            client,
            "evidence_links",
            f"/admin/v1/operator-review/cases/{case_id}/evidence-links?limit=5",
        ),
        _get_payload(
            client,
            "action_admission",
            f"/admin/v1/operator-review/cases/{case_id}/action-admission"
            "?action_type=RESOLVE",
        ),
    ]


def _get_payload(client: TestClient, name: str, path: str) -> SurfacePayload:
    response = client.get(path, headers=_admin_headers())
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


def _workbench_detail_summary_only(payload: Mapping[str, Any]) -> bool:
    evidence_links = payload.get("evidence_links")
    action_admission = payload.get("action_admission")
    if not isinstance(evidence_links, Mapping) or not isinstance(action_admission, Mapping):
        return False
    summary = evidence_links.get("summary")
    action_summary = action_admission.get("summary")
    return (
        evidence_links.get("inline_items_included") is False
        and action_admission.get("inline_items_included") is False
        and isinstance(summary, Mapping)
        and summary.get("evidence_source_status") == "READY"
        and summary.get("total_link_count") == 2
        and isinstance(action_summary, Mapping)
        and action_summary.get("preflight_only") is True
        and not _contains_forbidden_keys(payload, FORBIDDEN_KEYS)
    )


def _evidence_links_safe(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary")
    items = payload.get("items")
    if not isinstance(summary, Mapping) or not isinstance(items, list):
        return False
    hashes = _collect_hash_values(items)
    previews = _collect_preview_values(items)
    link_types = {item.get("link_type") for item in items if isinstance(item, Mapping)}
    return (
        summary.get("evidence_source_status") == "READY"
        and summary.get("operator_note_count") == 1
        and summary.get("redacted_evidence_export_count") == 1
        and summary.get("returned_link_count") == 2
        and link_types == {"operator_review_note", "redacted_evidence_export"}
        and hashes
        and all(_is_sha256_hex(value) for value in hashes)
        and all(isinstance(value, str) and len(value) <= 240 for value in previews)
        and not _contains_forbidden_keys(payload, FORBIDDEN_KEYS)
    )


def _action_admission_safe(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary")
    requested = payload.get("requested_action")
    items = payload.get("items")
    if not isinstance(summary, Mapping) or not isinstance(requested, Mapping):
        return False
    if not isinstance(items, list):
        return False
    return (
        summary.get("requested_action_type") == "RESOLVE"
        and summary.get("requested_action_admitted") is True
        and summary.get("preflight_only") is True
        and requested.get("requires_resolution_comment") is True
        and requested.get("mutation_route_authoritative") is True
        and requested.get("preflight_only") is True
        and all(_admission_item_safe(item) for item in items)
        and not _contains_forbidden_keys(payload, FORBIDDEN_KEYS)
    )


def _admission_item_safe(item: Any) -> bool:
    if not isinstance(item, Mapping):
        return False
    return (
        isinstance(item.get("action_type"), str)
        and isinstance(item.get("current_status"), str)
        and isinstance(item.get("target_status"), str)
        and isinstance(item.get("admitted"), bool)
        and item.get("mutation_route_authoritative") is True
        and item.get("preflight_only") is True
    )


def _evidence_item_redaction_safe(payload: Mapping[str, Any]) -> bool:
    items = payload.get("items")
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, Mapping):
            return False
        redaction = item.get("redaction")
        if not isinstance(redaction, Mapping):
            return False
        if not all(value is False for value in redaction.values()):
            return False
    return True


def _redaction_flags_safe(
    payload: Mapping[str, Any],
    required_flags: tuple[str, ...],
) -> bool:
    redaction = payload.get("redaction")
    if not isinstance(redaction, Mapping):
        return False
    return all(redaction.get(key) is False for key in required_flags)


def _collect_hash_values(value: Any) -> list[str]:
    hashes: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if (
                key in {"operator_note_hash", "evidence_hash", "resolution_hash"}
                and isinstance(child, str)
            ):
                hashes.append(child)
            hashes.extend(_collect_hash_values(child))
    elif isinstance(value, list):
        for item in value:
            hashes.extend(_collect_hash_values(item))
    return hashes


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


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _operator_ref() -> dict[str, str]:
    return {
        "operator_type": "user",
        "operator_id": "privacy-operator",
        "tenant_id": "privacy-tenant",
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_privacy_evidence_redacted(serialized_evidence: str) -> None:
    leaks = _leak_labels(serialized_evidence, FORBIDDEN_VALUES)
    if leaks:
        raise ValueError(
            "AG operator review case evidence/admission privacy evidence leaked "
            f"labels: {', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_case_evidence_admission_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_case_evidence_admission_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review case evidence/admission privacy regression."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_case_evidence_admission_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
