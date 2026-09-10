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
from nex_ag.operator_review_workbench import (  # noqa: E402
    register_operator_review_workbench_routes,
)
from nex_ag.operator_reviews import (  # noqa: E402
    OperatorEvidenceExportStore,
    OperatorReviewNoteStore,
    build_operator_evidence_export_record,
    build_operator_review_note_record,
    sha256_text,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ag_operator_review_workbench_privacy_regression.v1"
SLICE_ID = "0639"
SERVICE_ID = "nex-ag"
TARGET_SERVICE = "nex-ae-api"
TARGET_KIND = "operator_control.worker_result"
TARGET_ID = "worker-result-privacy-0639"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"

RAW_NOTE_SENTINEL = "RAW_NOTE_SECRET_0639_SHOULD_NOT_LEAK"
RAW_OPERATOR_NOTE = (
    "Privacy regression note preview budget filler. " * 7
    + RAW_NOTE_SENTINEL
)
RAW_EVIDENCE_BODY = "RAW_EVIDENCE_BODY_SECRET_0639_SHOULD_NOT_LEAK"
RAW_PROMPT = "RAW_PROMPT_SECRET_0639_SHOULD_NOT_LEAK"
RAW_SOURCE_TEXT = "RAW_SOURCE_TEXT_SECRET_0639_SHOULD_NOT_LEAK"
STORAGE_PATH = "/data/nex-platform/private/raw-0639.pdf"
IDEMPOTENCY_KEY = "idem-0639-secret-key"
PROVIDER_API_KEY = "provider-key-0639"
DATABASE_URL = "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_test"
SERVICE_TOKEN = "service-token-0639"

FORBIDDEN_VALUES = {
    "raw_operator_note_full_text": RAW_OPERATOR_NOTE,
    "raw_operator_note_sentinel": RAW_NOTE_SENTINEL,
    "raw_evidence_body": RAW_EVIDENCE_BODY,
    "raw_prompt": RAW_PROMPT,
    "raw_source_text": RAW_SOURCE_TEXT,
    "storage_path": STORAGE_PATH,
    "idempotency_key": IDEMPOTENCY_KEY,
    "provider_api_key": PROVIDER_API_KEY,
    "database_url": DATABASE_URL,
    "service_token": SERVICE_TOKEN,
}


@dataclass(frozen=True)
class SurfacePayload:
    name: str
    status_code: int
    payload: dict[str, Any]


def run_ag_operator_review_workbench_privacy_regression() -> dict[str, Any]:
    note_store, export_store = _build_fixture_stores()
    surfaces = _collect_surface_payloads(note_store, export_store)
    surface_checks = [_surface_privacy_check(surface) for surface in surfaces]
    workbench = next(surface for surface in surfaces if surface.name == "workbench")
    rollup = next(surface for surface in surfaces if surface.name == "rollups")
    dashboard = next(surface for surface in surfaces if surface.name == "dashboard")
    issue_candidates = next(
        surface for surface in surfaces if surface.name == "issue_candidates"
    )
    checks = {
        "all_routes_200": all(surface.status_code == 200 for surface in surfaces),
        "no_forbidden_values": all(not item["leak_labels"] for item in surface_checks),
        "workbench_preview_is_bounded": _workbench_preview_is_bounded(
            workbench.payload
        ),
        "workbench_raw_fields_absent": _workbench_raw_fields_absent(
            workbench.payload
        ),
        "rollup_redaction_flags_safe": _redaction_flags_safe(rollup.payload),
        "dashboard_redaction_flags_safe": _redaction_flags_safe(
            dashboard.payload.get("operator_review_workbench", {})
        ),
        "issue_candidates_reference_safe_sources": _issue_candidates_safe(
            issue_candidates.payload
        ),
    }
    evidence = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "failure_code": None
        if all(checks.values())
        else "ag_operator_review_workbench_privacy_regression_failed",
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
            "note_preview_limit": 240,
            "raw_note_length": len(RAW_OPERATOR_NOTE),
            "forbidden_value_labels": sorted(FORBIDDEN_VALUES),
        },
    }
    assert_privacy_evidence_redacted(json.dumps(evidence, default=str))
    return evidence


def _build_fixture_stores() -> tuple[OperatorReviewNoteStore, OperatorEvidenceExportStore]:
    note_store = OperatorReviewNoteStore()
    export_store = OperatorEvidenceExportStore()
    note_store.save(_unsafe_note_record())
    export_store.save(_unsafe_export_record())
    return note_store, export_store


def _unsafe_note_record() -> dict[str, Any]:
    record = build_operator_review_note_record(
        {
            "target_ref": _target_ref(),
            "operator_ref": _operator_ref(),
            "operator_note": RAW_OPERATOR_NOTE,
            "note_type": "OBSERVATION",
            "severity": "HIGH",
            "reason_codes": ["privacy_regression"],
            "metadata": {
                "idempotency_key_hash": sha256_text(IDEMPOTENCY_KEY),
                "source_view": "operator_review_workbench",
            },
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        created_at="2026-09-10T00:00:00Z",
    )
    return {
        **record,
        "operator_note": RAW_OPERATOR_NOTE,
        "raw_note": RAW_OPERATOR_NOTE,
        "metadata": {
            **dict(record.get("metadata") or {}),
            "idempotency_key": IDEMPOTENCY_KEY,
            "database_url": DATABASE_URL,
            "service_token": SERVICE_TOKEN,
        },
    }


def _unsafe_export_record() -> dict[str, Any]:
    record = build_operator_evidence_export_record(
        {
            "target_ref": _target_ref(),
            "operator_ref": _operator_ref(),
            "export_status": "FAILED",
            "export_format": "json",
            "evidence_refs": [
                {
                    "source_service": TARGET_SERVICE,
                    "evidence_type": "worker_result",
                    "evidence_id": TARGET_ID,
                    "relation": "operator_context",
                    "content_hash": "a" * 64,
                    "redaction_status": "HASH_ONLY",
                }
            ],
            "metadata": {
                "source_view": "operator_review_workbench",
            },
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        created_at="2026-09-10T00:05:00Z",
    )
    return {
        **record,
        "evidence_manifest": {
            **dict(record.get("evidence_manifest") or {}),
            "raw_body": RAW_EVIDENCE_BODY,
            "raw_prompt": RAW_PROMPT,
            "raw_source_text": RAW_SOURCE_TEXT,
            "storage_path": STORAGE_PATH,
        },
        "raw_prompt": RAW_PROMPT,
        "raw_source_text": RAW_SOURCE_TEXT,
        "storage_path": STORAGE_PATH,
        "provider_api_key": PROVIDER_API_KEY,
        "metadata": {
            **dict(record.get("metadata") or {}),
            "idempotency_key": IDEMPOTENCY_KEY,
            "service_token": SERVICE_TOKEN,
            "database_url": DATABASE_URL,
        },
    }


def _collect_surface_payloads(
    note_store: OperatorReviewNoteStore,
    export_store: OperatorEvidenceExportStore,
) -> list[SurfacePayload]:
    app = build_service_app(SERVICE_SPECS[SERVICE_ID])
    register_operator_review_workbench_routes(
        app,
        note_store=note_store,
        export_store=export_store,
    )
    register_unified_operation_routes(
        app,
        operator_review_note_store=note_store,
        operator_review_export_store=export_store,
    )
    client = TestClient(app)
    query = (
        f"target_service={TARGET_SERVICE}&target_kind={TARGET_KIND}"
        f"&target_id={TARGET_ID}&note_status=ACTIVE&export_status=FAILED"
    )
    return [
        _get_payload(
            client,
            "workbench",
            f"/admin/v1/operator-review/workbench?{query}",
            _admin_headers(),
        ),
        _get_payload(
            client,
            "rollups",
            f"/admin/v1/operator-review/workbench/rollups?{query}",
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


def _workbench_preview_is_bounded(payload: Mapping[str, Any]) -> bool:
    notes = [
        note
        for item in payload.get("items", [])
        if isinstance(item, Mapping)
        for note in item.get("notes", [])
        if isinstance(note, Mapping)
    ]
    if not notes:
        return False
    previews = [note.get("operator_note_preview") for note in notes]
    return all(
        isinstance(preview, str)
        and len(preview) <= 240
        and RAW_NOTE_SENTINEL not in preview
        for preview in previews
    )


def _workbench_raw_fields_absent(payload: Mapping[str, Any]) -> bool:
    return not _contains_forbidden_keys(
        payload,
        {
            "operator_note",
            "raw_note",
            "raw_body",
            "raw_prompt",
            "raw_source_text",
            "storage_path",
            "storage_uri",
            "provider_api_key",
            "database_url",
            "service_token",
            "idempotency_key",
            "evidence_manifest",
            "metadata",
        },
    )


def _redaction_flags_safe(payload: Mapping[str, Any]) -> bool:
    redaction = payload.get("redaction")
    if not isinstance(redaction, Mapping):
        return False
    return all(
        redaction.get(key) is False
        for key in (
            "raw_operator_note_included",
            "raw_evidence_body_included",
            "raw_prompt_included",
            "raw_source_text_included",
            "storage_paths_included",
            "idempotency_keys_included",
        )
    )


def _issue_candidates_safe(payload: Mapping[str, Any]) -> bool:
    candidates = payload.get("issue_candidates")
    if not isinstance(candidates, list):
        return False
    return any(
        isinstance(candidate, Mapping)
        and candidate.get("rule_id") == "operator_review_attention_required.v1"
        and isinstance(candidate.get("signal"), Mapping)
        and candidate["signal"].get("source_type") == "operator_review_workbench"
        for candidate in candidates
    )


def _contains_forbidden_keys(value: Any, forbidden_keys: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in forbidden_keys or _contains_forbidden_keys(child, forbidden_keys)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_keys(item, forbidden_keys) for item in value)
    return False


def _target_ref() -> dict[str, str]:
    return {
        "target_service": TARGET_SERVICE,
        "target_kind": TARGET_KIND,
        "target_id": TARGET_ID,
    }


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
            "AG operator review workbench privacy evidence leaked labels: "
            f"{', '.join(leaks)}"
        )


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ag_operator_review_workbench_privacy_regression=pass "
            f"surfaces={evidence['surface_count']} "
            f"forbidden_labels={len(evidence['fixture']['forbidden_value_labels'])}"
        )
    failed = [
        name for name, passed in evidence.get("checks", {}).items() if not passed
    ]
    return (
        "ag_operator_review_workbench_privacy_regression=fail "
        f"reason={evidence.get('failure_code')} "
        f"failed_checks={','.join(failed)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AG operator review workbench privacy regression audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operator_review_workbench_privacy_regression()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
