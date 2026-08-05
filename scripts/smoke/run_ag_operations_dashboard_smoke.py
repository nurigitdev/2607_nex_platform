#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ag",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ag.operations import (  # noqa: E402
    AgOperationsSourceRuntime,
    build_operations_source_registry,
    register_job_operation_routes,
    register_operation_source_readiness_routes,
    register_operational_event_taxonomy_routes,
    register_operational_event_routes,
    register_unified_operation_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_common_job,
    build_operational_event,
    build_service_app,
    build_subject_ref,
    issue_mock_service_token,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"
SCHEMA_VERSION = "ag_operations_dashboard_smoke.v1"


def run_ag_operations_dashboard_smoke() -> dict[str, Any]:
    registry = build_operations_source_registry(
        job_queues=_build_job_queues(),
        event_stores=_build_event_stores(),
    )
    runtime = AgOperationsSourceRuntime(
        mode="memory",
        profile="dev",
        selected_service_ids=tuple(registry.service_ids()),
        registry=registry,
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_operation_source_readiness_routes(app, runtime=runtime)
    register_unified_operation_routes(app, registry=registry, runtime=runtime)
    register_operational_event_taxonomy_routes(app)
    register_operational_event_routes(app, registry=registry)
    register_job_operation_routes(app, registry=registry)

    client = TestClient(app)
    projections = _read_operations_projections(client)
    checks = _ag_operations_dashboard_smoke_checks(projections)
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": status,
        "trace_id": TRACE_ID,
        "endpoint_count": len(projections),
        "projection_versions": {
            name: projection.get("projection_schema_version")
            for name, projection in projections.items()
        },
        "counts": _projection_counts(projections),
        "checks": checks,
    }


def _build_job_queues() -> dict[str, InMemoryJobQueue]:
    cx_queue = InMemoryJobQueue()
    cx_queue.enqueue(
        _sample_job(
            job_id="smoke-job-cx-001",
            idempotency_key="smoke-idem-cx-001",
            created_at="2026-08-05T00:00:00Z",
        )
    )
    cx_queue.start_job(
        "smoke-job-cx-001",
        updated_at="2026-08-05T00:00:03Z",
    )
    cx_queue.enqueue(
        _sample_job(
            job_id="smoke-job-cx-002",
            idempotency_key="smoke-idem-cx-002",
            created_at="2026-08-05T00:00:01Z",
        )
    )
    cx_queue.fail_job(
        cx_queue.start_job(
            "smoke-job-cx-002",
            updated_at="2026-08-05T00:00:04Z",
        )["job_id"],
        updated_at="2026-08-05T00:00:05Z",
    )
    ae_queue = InMemoryJobQueue()
    ae_queue.enqueue(
        _sample_job(
            job_id="smoke-job-ae-001",
            job_type="ae.artifact_render",
            subject_ref=build_subject_ref("ae.artifact", "artifact-smoke-001"),
            idempotency_key="smoke-idem-ae-001",
            created_at="2026-08-05T00:00:02Z",
        )
    )
    return {
        "nex-ae-api": ae_queue,
        "nex-cx": cx_queue,
    }


def _build_event_stores() -> dict[str, InMemoryOperationalEventStore]:
    cx_store = InMemoryOperationalEventStore()
    cx_store.append(
        build_operational_event(
            event_id="smoke-event-cx-001",
            service_id="nex-cx",
            event_type="cx.processing.succeeded",
            severity="INFO",
            message="Smoke document processing succeeded.",
            trace_id=TRACE_ID,
            request_id=REQUEST_ID,
            subject_ref={"type": "cx.document", "id": "doc-smoke-001"},
            details={"job_id": "smoke-job-cx-001"},
            created_at="2026-08-05T00:00:00Z",
        )
    )
    mo_store = InMemoryOperationalEventStore()
    mo_store.append(
        build_operational_event(
            event_id="smoke-event-mo-001",
            service_id="nex-mo",
            event_type="mo.provider.failed",
            severity="ERROR",
            message="Smoke provider request failed.",
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            request_id=REQUEST_ID,
            subject_ref={"type": "mo.provider", "id": "embedding"},
            details={"authorization": "Bearer private"},
            created_at="2026-08-05T00:00:01Z",
        )
    )
    return {
        "nex-cx": cx_store,
        "nex-mo": mo_store,
    }


def _sample_job(**overrides: Any) -> dict[str, Any]:
    return build_common_job(
        job_id=overrides.pop("job_id", "smoke-job-001"),
        job_type=overrides.pop("job_type", "cx.document_processing"),
        trace_id=overrides.pop("trace_id", TRACE_ID),
        request_id=overrides.pop("request_id", REQUEST_ID),
        subject_ref=overrides.pop(
            "subject_ref",
            build_subject_ref("cx.document", "doc-smoke-001"),
        ),
        idempotency_key=overrides.pop("idempotency_key", "smoke-idem-001"),
        created_at=overrides.pop("created_at", "2026-08-05T00:00:00Z"),
        max_attempts=overrides.pop("max_attempts", 2),
        status=overrides.pop("status", "QUEUED"),
        **overrides,
    )


def _read_operations_projections(client: TestClient) -> dict[str, dict[str, Any]]:
    return {
        "sources": _get_json(
            client,
            "/admin/v1/operations/sources",
            params={"service_id": "nex-cx"},
        ),
        "unified": _get_json(
            client,
            "/admin/v1/operations",
            params={"service_id": "nex-cx", "limit": 10},
        ),
        "event_taxonomy": _get_json(
            client,
            "/admin/v1/operations/event-taxonomy",
            params={"service_id": "nex-cx"},
        ),
        "events": _get_json(
            client,
            "/admin/v1/operations/events",
            params={"service_id": "nex-mo", "severity": "ERROR"},
        ),
        "event_detail": _get_json(
            client,
            "/admin/v1/operations/events/smoke-event-mo-001",
        ),
        "jobs": _get_json(
            client,
            "/admin/v1/operations/jobs",
            params={"service_id": "nex-cx"},
        ),
        "job_detail": _get_json(
            client,
            "/admin/v1/operations/jobs/nex-cx/smoke-job-cx-001",
        ),
        "trace_timeline": _get_json(
            client,
            f"/admin/v1/operations/traces/{TRACE_ID}",
            params={"service_id": "nex-cx"},
        ),
        "rollups": _get_json(
            client,
            "/admin/v1/operations/rollups",
            params={"service_id": "nex-cx"},
        ),
        "dashboard": _get_json(
            client,
            "/admin/v1/operations/dashboard",
            params={"service_id": "nex-cx", "recent_limit": 2},
        ),
        "issue_candidates": _get_json(
            client,
            "/admin/v1/operations/issue-candidates",
            params={"service_id": "nex-cx", "recent_limit": 2},
        ),
    }


def _get_json(
    client: TestClient,
    path: str,
    *,
    params: dict[str, object] | None = None,
) -> dict[str, Any]:
    response = client.get(path, params=params, headers=_ag_service_headers())
    response.raise_for_status()
    return response.json()


def _ag_service_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _ag_operations_dashboard_smoke_checks(
    projections: dict[str, dict[str, Any]],
) -> dict[str, bool]:
    dashboard = projections["dashboard"]
    issue_candidates = projections["issue_candidates"]
    event_detail = projections["event_detail"]
    job_detail = projections["job_detail"]
    trace_timeline = projections["trace_timeline"]
    expected_versions = {
        "sources": "ag_operation_source_readiness_projection.v1",
        "unified": "ag_unified_operations_projection.v1",
        "event_taxonomy": "ag_operational_event_taxonomy_projection.v1",
        "events": "ag_operational_event_projection.v1",
        "event_detail": "ag_operational_event_detail_projection.v1",
        "jobs": "ag_job_operations_projection.v1",
        "job_detail": "ag_job_operation_detail_projection.v1",
        "trace_timeline": "ag_cross_service_trace_timeline_projection.v1",
        "rollups": "ag_operations_rollup_metrics_projection.v1",
        "dashboard": "ag_operations_dashboard_snapshot_projection.v1",
        "issue_candidates": "ag_operations_issue_candidate_projection.v1",
    }
    return {
        "projection_versions": all(
            projections[name].get("projection_schema_version") == version
            for name, version in expected_versions.items()
        ),
        "source_ready": projections["sources"]["sources"][0]["readiness_status"] == "READY",
        "unified_jobs_and_events_visible": (
            projections["unified"]["jobs"]["summary"]["total"] == 2
            and projections["unified"]["events"]["summary"]["total"] == 1
        ),
        "event_detail_redacted": "private" not in json.dumps(
            event_detail,
            ensure_ascii=False,
        ),
        "job_detail_timeline_ready": (
            job_detail["lifecycle_timeline"]["timeline_status"] == "READY"
        ),
        "trace_timeline_mixes_jobs_events": {
            item["timeline_item_type"]
            for item in trace_timeline["timeline"]
        } == {"job", "event"},
        "rollup_counts": (
            projections["rollups"]["rollups"][0]["jobs"]["total"] == 2
            and projections["rollups"]["rollups"][0]["events"]["total"] == 1
        ),
        "dashboard_failure_and_active_jobs": (
            dashboard["recent_failures"]["jobs"][0]["job_id"] == "smoke-job-cx-002"
            and dashboard["active_jobs"][0]["job_id"] == "smoke-job-cx-001"
        ),
        "issue_candidates_include_failed_and_active": {
            candidate["rule_id"]
            for candidate in issue_candidates["issue_candidates"]
        } == {"failed_jobs_present.v1", "active_jobs_review.v1"},
    }


def _projection_counts(projections: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        "sources": len(projections["sources"]["sources"]),
        "events": len(projections["events"]["events"]),
        "jobs": len(projections["jobs"]["jobs"]),
        "trace_timeline": len(projections["trace_timeline"]["timeline"]),
        "rollups": len(projections["rollups"]["rollups"]),
        "dashboard_degraded_sources": len(projections["dashboard"]["degraded_sources"]),
        "issue_candidates": len(projections["issue_candidates"]["issue_candidates"]),
    }


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_operations_dashboard_smoke=pass "
            f"endpoints={evidence['endpoint_count']} "
            f"jobs={counts['jobs']} events={counts['events']} "
            f"issues={counts['issue_candidates']}"
        )
    return "ag_operations_dashboard_smoke=fail"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run mock-first AG operations dashboard smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_ag_operations_dashboard_smoke()
    output = summary_line(evidence) if args.summary else json.dumps(evidence, ensure_ascii=False)
    print(output)
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
