#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-ag"):
    sys.path.insert(0, str(path))

from nex_ag.cross_service_trace import (  # noqa: E402
    AgTraceSourceError,
    CrossServiceTraceAggregator,
    register_cross_service_trace_routes,
)
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    SqlAlchemyOperationalEventStore,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    build_service_app,
    issue_mock_service_token,
)

SCHEMA_VERSION = "ag_cross_service_trace_deterministic_e2e.v1"
TRACE_ID = "13791379137913791379137913791379"
OWNER_DIGEST = "a" * 64
PRIVATE_SENTINEL = "PRIVATE-PROMPT-MUST-NOT-LEAK"
CHECKED_AT = datetime(2026, 10, 6, 15, 10, tzinfo=UTC)
SERVICE_IDS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo")


class _FixtureClient:
    def __init__(self, service_id: str, stages: list[dict[str, Any]]) -> None:
        self.service_id = service_id
        self._stages = stages

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        del request_id, request_trace_id
        return build_cross_service_trace_source_projection(
            service_id=self.service_id,
            trace_id=trace_id,
            stages=deepcopy(self._stages),
            source_status="READY",
            checked_at=CHECKED_AT.isoformat().replace("+00:00", "Z"),
        )


class _UnavailableClient:
    service_id = "nex-mo"

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        del trace_id, request_id, request_trace_id
        raise AgTraceSourceError(
            self.service_id,
            "ag.trace_source_timeout",
            "UNAVAILABLE",
        )


class _PrivatePayloadClient(_FixtureClient):
    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        projection = super().get_trace_projection(
            trace_id,
            request_id=request_id,
            request_trace_id=request_trace_id,
        )
        projection["prompt"] = PRIVATE_SENTINEL
        return projection


def run_ag_cross_service_trace_deterministic_e2e(
    root: Path = ROOT,
    *,
    database_path: Path | None = None,
) -> dict[str, Any]:
    if database_path is None:
        with TemporaryDirectory(prefix="nex-ag-trace-1379-") as temp_dir:
            return _run_e2e(root, Path(temp_dir) / "ag-audit.sqlite3")
    return _run_e2e(root, database_path)


def _run_e2e(root: Path, database_path: Path) -> dict[str, Any]:
    clients = _fixture_clients()
    aggregator = CrossServiceTraceAggregator(clients, clock=lambda: CHECKED_AT)
    first = aggregator.aggregate(
        TRACE_ID,
        request_id="request-deterministic-1379",
        request_trace_id=TRACE_ID,
    )
    second = aggregator.aggregate(
        TRACE_ID,
        request_id="request-deterministic-1379",
        request_trace_id=TRACE_ID,
    )

    unavailable_clients = dict(clients)
    unavailable_clients["nex-mo"] = _UnavailableClient()
    partial = CrossServiceTraceAggregator(
        unavailable_clients,
        clock=lambda: CHECKED_AT,
    ).aggregate(
        TRACE_ID,
        request_id="request-partial-1379",
        request_trace_id=TRACE_ID,
    )

    private_clients = dict(clients)
    private_clients["nex-cx"] = _PrivatePayloadClient(
        "nex-cx",
        _fixture_stages()["nex-cx"],
    )
    private_rejected = CrossServiceTraceAggregator(
        private_clients,
        clock=lambda: CHECKED_AT,
    ).aggregate(
        TRACE_ID,
        request_id="request-private-1379",
        request_trace_id=TRACE_ID,
    )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    first_store, first_engine = _sqlite_event_store(database_path, initialize=True)
    first_response = _request_trace(aggregator, first_store, "request-route-1379-a")
    before_restart = first_store.list_events(trace_id=TRACE_ID)
    first_engine.dispose()

    restarted_store, restarted_engine = _sqlite_event_store(
        database_path,
        initialize=False,
    )
    recovered = restarted_store.list_events(trace_id=TRACE_ID)
    second_response = _request_trace(
        aggregator,
        restarted_store,
        "request-route-1379-b",
    )
    after_restart = restarted_store.list_events(trace_id=TRACE_ID)
    restarted_engine.dispose()

    schema = _load_json(
        root / "contracts/schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json"
    )
    first_payload = first_response.json()
    second_payload = second_response.json()
    serialized = json.dumps(
        {
            "success": first.projection,
            "partial": partial.projection,
            "private_rejected": private_rejected.projection,
            "diagnostics": [*partial.diagnostics, *private_rejected.diagnostics],
            "events": after_restart,
            "responses": [first_payload, second_payload],
        },
        sort_keys=True,
    )
    families = {item["stage_family"] for item in first_payload.get("timeline", [])}
    partial_statuses = _source_statuses(partial.projection)
    private_statuses = _source_statuses(private_rejected.projection)
    checks = {
        "success_projection_is_deterministic": first == second,
        "success_sources_are_ready": first.projection.get("projection_status")
        == "READY"
        and all(
            value == "READY" for value in _source_statuses(first.projection).values()
        ),
        "all_stage_families_projected": families
        == {
            "AUTH",
            "UPLOAD",
            "INGESTION",
            "RETRIEVAL",
            "GENERATION",
            "ARTIFACT",
            "ACCESS",
            "OPERATIONS",
        },
        "timeline_order_is_stable": [
            item["operation_timestamp"] for item in first.projection["timeline"]
        ]
        == sorted(item["operation_timestamp"] for item in first.projection["timeline"]),
        "partial_failure_is_isolated": partial_statuses.get("nex-mo") == "UNAVAILABLE"
        and partial.projection.get("projection_status") == "DEGRADED"
        and partial.projection.get("summary", {}).get("source_count") == 4,
        "healthy_partial_sources_survive": {
            item["service_id"] for item in partial.projection.get("timeline", [])
        }
        == {"nex-oa", "nex-ae-api", "nex-cx"},
        "partial_diagnostic_is_bounded": partial.diagnostics
        == (
            {
                "service_id": "nex-mo",
                "error_code": "ag.trace_source_timeout",
                "retryable": True,
                "status_code": 503,
            },
        ),
        "private_contract_violation_is_rejected": private_statuses.get("nex-cx")
        == "DEGRADED"
        and not any(
            item["service_id"] == "nex-cx"
            for item in private_rejected.projection.get("timeline", [])
        ),
        "private_diagnostic_is_bounded": private_rejected.diagnostics
        == (
            {
                "service_id": "nex-cx",
                "error_code": "ag.trace_source_contract_invalid",
                "retryable": False,
                "status_code": 502,
            },
        ),
        "private_payload_is_absent": PRIVATE_SENTINEL not in serialized
        and all(
            forbidden not in serialized.lower()
            for forbidden in (
                "bearer ",
                "provider_url",
                "database_url",
                "storage_ref",
                "generated_text",
            )
        ),
        "first_route_response_is_valid": first_response.status_code == 200
        and _validates(schema, first_payload),
        "audit_is_present_before_restart": len(before_restart) == 1,
        "audit_survives_restart": recovered == before_restart,
        "route_succeeds_after_restart": second_response.status_code == 200
        and _validates(schema, second_payload),
        "audit_continues_after_restart": len(after_restart) == 2
        and {event["request_id"] for event in after_restart}
        == {"request-route-1379-a", "request-route-1379-b"},
        "audit_events_are_metadata_only": all(
            event.get("details", {}).get("private_payload_included") is False
            for event in after_restart
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1379",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "success_stage_count": first_payload.get("summary", {}).get(
                "stage_count", 0
            ),
            "stage_family_count": len(families),
            "partial_diagnostic_count": len(partial.diagnostics),
            "restart_audit_event_count": len(after_restart),
        },
        "decision": {
            "database_mode": "sqlite_regression",
            "postgres_required": False,
            "remote_provider_required": False,
            "postgres_evidence_slice": "1380",
            "next_slice": "1380" if passed else "blocked",
        },
    }


def _fixture_clients() -> dict[str, _FixtureClient]:
    return {
        service_id: _FixtureClient(service_id, stages)
        for service_id, stages in _fixture_stages().items()
    }


def _fixture_stages() -> dict[str, list[dict[str, Any]]]:
    definitions = {
        "nex-oa": [("auth", "AUTH", "2026-10-06T15:00:00Z")],
        "nex-ae-api": [
            ("upload", "UPLOAD", "2026-10-06T15:01:00Z"),
            ("artifact", "ARTIFACT", "2026-10-06T15:07:00Z"),
            ("access", "ACCESS", "2026-10-06T15:08:00Z"),
        ],
        "nex-cx": [
            ("ingestion", "INGESTION", "2026-10-06T15:02:00Z"),
            ("retrieval", "RETRIEVAL", "2026-10-06T15:03:00Z"),
            ("generation", "GENERATION", "2026-10-06T15:06:00Z"),
        ],
        "nex-mo": [("provider", "GENERATION", "2026-10-06T15:05:00Z")],
    }
    return {
        service_id: [
            build_cross_service_trace_stage(
                stage_id=f"{service_id}-{name}-1379",
                trace_id=TRACE_ID,
                request_id=f"request-{service_id}-{name}",
                service_id=service_id,
                stage_family=family,
                stage_status="SUCCEEDED",
                operation_timestamp=timestamp,
                owner_digest=OWNER_DIGEST if service_id != "nex-mo" else None,
                safe_attributes={"result_code": "READY"},
            )
            for name, family, timestamp in service_definitions
        ]
        for service_id, service_definitions in definitions.items()
    }


def _request_trace(
    aggregator: CrossServiceTraceAggregator,
    store: SqlAlchemyOperationalEventStore,
    request_id: str,
):
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cross_service_trace_routes(app, aggregator=aggregator, event_store=store)
    token = issue_mock_service_token(
        service_id="nex-oa",
        audience="nex-ag",
    ).access_token
    return TestClient(app).get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": request_id,
            "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        },
    )


def _sqlite_event_store(
    database_path: Path,
    *,
    initialize: bool,
) -> tuple[SqlAlchemyOperationalEventStore, Any]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    if initialize:
        with engine.begin() as connection:
            connection.execute(text("""
                    CREATE TABLE service_operational_events (
                        event_id TEXT PRIMARY KEY,
                        event_schema_version TEXT NOT NULL,
                        service_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        trace_id TEXT,
                        request_id TEXT,
                        subject_type TEXT,
                        subject_id TEXT,
                        message TEXT NOT NULL,
                        details TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return SqlAlchemyOperationalEventStore(factory), engine


def _source_statuses(projection: dict[str, Any]) -> dict[str, str]:
    return {
        item["service_id"]: item["source_status"]
        for item in projection.get("source_statuses", [])
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _validates(schema: Any, payload: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    try:
        Draft202012Validator(schema).validate(payload)
    except Exception:
        return False
    return True


def summary_line(result: dict[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ag_cross_service_trace_deterministic_e2e="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"families={summary.get('stage_family_count', 0)} "
        f"partial_diagnostics={summary.get('partial_diagnostic_count', 0)} "
        f"restart_audits={summary.get('restart_audit_event_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ag_cross_service_trace_deterministic_e2e()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
