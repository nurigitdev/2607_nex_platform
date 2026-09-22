#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_cx.hybrid_retrieval_package import (  # noqa: E402
    HybridRetrievalPackageError,
)
from nex_cx.ingestion import ContentIngestionStore  # noqa: E402
from nex_cx.retrieval import register_retrieval_routes  # noqa: E402
from nex_cx.retrieval_observability import (  # noqa: E402
    CX_RETRIEVAL_PACKAGE_FAILED_EVENT,
    CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT,
)


SCHEMA_VERSION = "cx_retrieval_operations_observability_contract.v1"
TRACE_ID = "94800000000000000000000000000002"
PRIVATE_QUERY = "PRIVATE_S95_OBSERVABILITY_QUERY"
PRIVATE_EVIDENCE = "PRIVATE_S95_OBSERVABILITY_EVIDENCE"


class _Runtime:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result

    def build_package(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def run_cx_retrieval_operations_observability() -> dict[str, Any]:
    success_client, success_events = _client(_Runtime(_package()))
    first = success_client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )
    second = success_client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )
    observed = success_events.list_events(
        event_type=CX_RETRIEVAL_PACKAGE_OBSERVED_EVENT
    )

    failure_client, failure_events = _client(
        _Runtime(
            HybridRetrievalPackageError(
                status_code=503,
                error_code="CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE",
                detail="provider private detail",
                retryable=True,
            )
        )
    )
    failed = failure_client.post(
        "/api/v1/retrieval/context",
        headers=_headers(),
        json=_payload(),
    )
    failure_records = failure_events.list_events(
        event_type=CX_RETRIEVAL_PACKAGE_FAILED_EVENT
    )
    serialized_events = json.dumps(
        {"success": observed, "failure": failure_records},
        sort_keys=True,
    )
    success_event = observed[0] if observed else {}
    failure_event = failure_records[0] if failure_records else {}
    checks = {
        "success_api_preserved": (
            first.status_code == 200 and second.status_code == 200
        ),
        "success_event_emitted_once": len(observed) == 1,
        "success_event_correlated": (
            success_event.get("trace_id") == TRACE_ID
            and success_event.get("request_id") == "request-0948-contract"
        ),
        "success_event_metadata_only": (
            success_event.get("details", {}).get("retrieval_status") == "READY"
            and success_event.get("details", {}).get("evidence_count") == 1
            and success_event.get("details", {}).get("rerank_state") == "APPLIED"
        ),
        "success_event_deterministic": (
            success_event.get("subject_ref", {}).get("id")
            == "package-0948-contract"
        ),
        "failure_api_preserved": (
            failed.status_code == 503
            and failed.json().get("error_code")
            == "CX_HYBRID_CANDIDATE_PROVIDER_UNAVAILABLE"
        ),
        "failure_event_emitted": len(failure_records) == 1,
        "failure_event_actionable": (
            failure_event.get("details", {}).get("failure_stage")
            == "package_build"
            and failure_event.get("details", {}).get("retryable") is True
            and failure_event.get("details", {}).get("runtime_mode") == "hardened"
        ),
        "failure_detail_redacted": "provider private detail" not in serialized_events,
        "private_payload_absent": (
            PRIVATE_QUERY not in serialized_events
            and PRIVATE_EVIDENCE not in serialized_events
            and "owner-contract" not in serialized_events
            and "document-contract" not in serialized_events
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "contract_schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed_checks,
        "success_event_type": success_event.get("event_type"),
        "failure_event_type": failure_event.get("event_type"),
        "postgres_required": False,
        "remote_provider_required": False,
    }


def _client(
    runtime: _Runtime,
) -> tuple[TestClient, InMemoryOperationalEventStore]:
    events = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=events)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_retrieval_routes(
        app,
        store=ContentIngestionStore(),
        hybrid_runtime=runtime,
        event_emitter=emitter,
    )
    return TestClient(app), events


def _payload() -> dict[str, Any]:
    return {
        "query_text": PRIVATE_QUERY,
        "document_scope": {"document_ids": ["document-contract"]},
    }


def _package() -> dict[str, Any]:
    return {
        "retrieval_package_id": "package-0948-contract",
        "retrieval_runtime_schema_version": "cx_hybrid_retrieval_runtime.v1",
        "status": "READY",
        "trace_id": TRACE_ID,
        "request_id": "request-0948-contract",
        "query_text": PRIVATE_QUERY,
        "retrieval_profile": {
            "quality_policy": {"policy_id": "weighted_rrf_vector_bm25_v1"}
        },
        "permission_snapshot": {
            "actor_id": "owner-contract",
            "policy_version": "cx.private_owner_active.v1",
        },
        "score_summary": {"rerank_state": "APPLIED"},
        "source_summary": {"document_count": 1, "chunk_count": 1},
        "evidence_items": [
            {
                "content_object_id": "document-contract",
                "text": PRIVATE_EVIDENCE,
            }
        ],
        "warnings": [],
        "no_answer_reason": None,
    }


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "X-NEX-Tenant-ID": "tenant-contract",
        "X-NEX-Subject-ID": "owner-contract",
        "X-Request-ID": "request-0948-contract",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "cx_retrieval_operations_observability="
        f"{str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "postgres_required=False remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_retrieval_operations_observability()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
