#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.upload_progress import register_upload_progress_routes  # noqa: E402
from nex_ae_api.uploads import UploadHandoffStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    DEFAULT_USER_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


SCHEMA_VERSION = "ae_upload_ingestion_progress_evidence.v1"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TENANT_ID = "tenant-1348"
OWNER_ID = "owner-1348"
DOCUMENT_ID = "document-1348"
VECTOR_INDEX_ID = "11111111-1111-4111-8111-111111111111"


class EvidenceCxProgressClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def list_ingestion_runs(self, document_id: str, **kwargs: str) -> dict[str, Any]:
        self.calls.append({"operation": "runs", "document_id": document_id, **kwargs})
        return {
            "document_id": DOCUMENT_ID,
            "runs": [
                {
                    "run_id": "run-1348",
                    "document_id": DOCUMENT_ID,
                    "status": "SUCCEEDED",
                    "current_step": None,
                    "step_total": 4,
                    "step_completed": 4,
                    "attempt_count": 1,
                    "max_attempts": 4,
                    "checkpoint_version": 7,
                    "retry_at": None,
                    "last_error": None,
                    "updated_at": "2026-10-05T01:01:00Z",
                    "steps": [
                        {
                            "step_id": "embedding_index",
                            "output_ref": f"cx.vector_index:{VECTOR_INDEX_ID}",
                        }
                    ],
                }
            ],
        }

    def get_vector_readiness(
        self,
        vector_index_id: str,
        **kwargs: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"operation": "readiness", "vector_index_id": vector_index_id, **kwargs}
        )
        return {
            "vector_index_id": VECTOR_INDEX_ID,
            "status": "READY",
            "freshness_status": "READY",
            "freshness_reason": None,
            "retrieval_usable": True,
            "rebuild_required": False,
            "expected_vector_count": 3,
            "actual_vector_count": 3,
        }


def run_ae_upload_ingestion_progress() -> dict[str, Any]:
    store = UploadHandoffStore()
    store.save(_handoff())
    cx_client = EvidenceCxProgressClient()
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_upload_progress_routes(app, upload_store=store, cx_client=cx_client)

    with TestClient(app) as client:
        owner = client.get(
            "/api/v1/uploads/handoff-1348/progress",
            headers=_headers(OWNER_ID),
        )
        hidden = client.get(
            "/api/v1/uploads/handoff-1348/progress",
            headers=_headers("other-owner"),
        )
        unauthorized = client.get("/api/v1/uploads/handoff-1348/progress")

    projection = owner.json()
    evidence = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1348",
        "requirement": "S135",
        "owner_status_code": owner.status_code,
        "other_owner_status_code": hidden.status_code,
        "unauthorized_status_code": unauthorized.status_code,
        "journey_status": projection.get("status"),
        "progress_percent": projection.get("progress_percent"),
        "freshness_status": (projection.get("vector_index") or {}).get(
            "freshness_status"
        ),
        "retrieval_usable": (projection.get("vector_index") or {}).get(
            "retrieval_usable"
        ),
        "dependency_call_count": len(cx_client.calls),
        "next_slice": "1349",
    }
    serialized_projection = json.dumps(projection, sort_keys=True).lower()
    calls = cx_client.calls
    checks = {
        "owner_read_succeeds": owner.status_code == 200,
        "other_owner_hidden": hidden.status_code == 404,
        "authentication_required": unauthorized.status_code == 401,
        "index_ready": projection.get("status") == "INDEX_READY",
        "progress_complete": projection.get("progress_percent") == 100,
        "freshness_ready": evidence["freshness_status"] == "READY",
        "retrieval_usable": evidence["retrieval_usable"] is True,
        "owner_scope_forwarded": all(
            call.get("tenant_id") == TENANT_ID
            and call.get("owner_user_id") == OWNER_ID
            for call in calls
        ),
        "only_owner_dependencies_called": len(calls) == 2,
        "private_payload_absent": all(
            forbidden not in serialized_projection
            for forbidden in (
                '"content_text"',
                '"content_base64"',
                '"chunk_text"',
                '"embedding"',
                '"vector"',
                '"api_key"',
                '"access_token"',
            )
        ),
        "privacy_flags_closed": all(
            value is False
            for key, value in (projection.get("metadata") or {}).items()
            if key != "owner_scoped"
        ),
        "owner_scope_declared": (projection.get("metadata") or {}).get(
            "owner_scoped"
        )
        is True,
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        **evidence,
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "private_payload_in_evidence": False,
    }


def _handoff() -> dict[str, Any]:
    return {
        "upload_handoff_id": "handoff-1348",
        "workspace_id": "workspace-1348",
        "tenant_id": TENANT_ID,
        "owner_user_id": OWNER_ID,
        "cx_document_ref": {
            "document_id": DOCUMENT_ID,
            "upload_id": "upload-1348",
            "ingestion_job_id": "job-1348",
        },
    }


def _headers(owner_id: str) -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id=TENANT_ID,
        user_id=owner_id,
        scopes=[DEFAULT_USER_SCOPE],
        roles=["employee"],
    )
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-Request-ID": "request-1348",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"ae_upload_progress=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    return (
        "ae_upload_progress=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"status={evidence.get('journey_status')} "
        f"freshness={evidence.get('freshness_status')} "
        f"next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_upload_ingestion_progress()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
