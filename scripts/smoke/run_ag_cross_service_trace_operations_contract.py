#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-ag"):
    sys.path.insert(0, str(path))

from nex_ag.cross_service_trace import (  # noqa: E402
    CrossServiceTraceAggregator,
    register_cross_service_trace_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    SERVICE_SPECS,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    build_service_app,
    issue_mock_service_token,
)

SCHEMA_VERSION = "ag_cross_service_trace_operations_contract_evidence.v1"
TRACE_ID = "13781378137813781378137813781378"


class _SourceClient:
    def __init__(self, service_id: str) -> None:
        self.service_id = service_id

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        del request_id, request_trace_id
        stage = build_cross_service_trace_stage(
            stage_id=f"stage-{self.service_id}-1378",
            trace_id=trace_id,
            request_id=f"request-{self.service_id}-1378",
            service_id=self.service_id,
            stage_family="OPERATIONS",
            stage_status="SUCCEEDED",
            operation_timestamp="2026-10-06T14:00:00Z",
            safe_attributes={"result_code": "READY"},
        )
        return build_cross_service_trace_source_projection(
            service_id=self.service_id,
            trace_id=trace_id,
            stages=[stage],
            source_status="READY",
            checked_at="2026-10-06T14:01:00Z",
        )


def run_ag_cross_service_trace_operations_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    store = InMemoryOperationalEventStore()
    aggregator = CrossServiceTraceAggregator(
        {
            service_id: _SourceClient(service_id)
            for service_id in ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo")
        },
        clock=lambda: datetime(2026, 10, 6, 14, 1, tzinfo=UTC),
    )
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_cross_service_trace_routes(
        app,
        aggregator=aggregator,
        event_store=store,
    )
    token = issue_mock_service_token(
        service_id="nex-oa", audience="nex-ag"
    ).access_token
    response = TestClient(app).get(
        f"/admin/v1/operations/traces/{TRACE_ID}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Request-ID": "request-route-1378",
            "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
        },
    )
    payload = response.json()
    events = store.list_events(trace_id=TRACE_ID)
    schema = _load_json(
        root / "contracts/schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json"
    )
    openapi = _load_yaml(root / "contracts/openapi/nex-ag.openapi.yaml")
    operation = (
        openapi.get("paths", {})
        .get("/admin/v1/operations/traces/{trace_id}", {})
        .get("get", {})
    )
    route_source = _read_text(root / "services/nex-ag/nex_ag/cross_service_trace.py")
    legacy_source = _read_text(root / "services/nex-ag/nex_ag/operations.py")
    main_source = _read_text(root / "services/nex-ag/nex_ag/main.py")
    migration = _read_text(
        root
        / "database/nex-ag/migrations/0085_service_operational_events_foundation.sql"
    )
    serialized = json.dumps({"payload": payload, "events": events}, sort_keys=True)
    checks = {
        "protected_route_succeeds": response.status_code == 200,
        "e2e_contract_valid": _validates(schema, payload),
        "five_sources_projected": payload.get("summary", {}).get("source_count") == 5,
        "ag_audit_stage_present": any(
            item.get("service_id") == "nex-ag"
            and item.get("stage_family") == "OPERATIONS"
            for item in payload.get("timeline", [])
        ),
        "durable_audit_emitted": len(events) == 1
        and events[0].get("event_type") == "ag.cross_service_trace.read.succeeded",
        "audit_is_metadata_only": events[0]
        .get("details", {})
        .get("private_payload_included")
        is False,
        "legacy_database_route_removed": (
            "/admin/v1/operations/traces/{trace_id}" not in legacy_source
            and "register_cross_service_trace_routes" in main_source
        ),
        "durable_store_wired": (
            "SERVICE_PERSISTENCE.operational_event_store" in main_source
        ),
        "openapi_uses_e2e_contract": operation.get("responses", {})
        .get("200", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref")
        == "#/components/schemas/AgCrossServiceTraceE2E",
        "openapi_has_trace_only_parameter": len(operation.get("parameters", [])) == 1,
        "existing_trace_index_reused": (
            "ix_service_operational_events_trace" in migration
            and not (
                root
                / "database/nex-ag/migrations/1378_ag_cross_service_trace_audit.sql"
            ).exists()
        ),
        "private_payload_absent": all(
            token not in serialized
            for token in (
                "prompt",
                "generated_text",
                "provider_url",
                "database_url",
                "storage_ref",
                "authorization",
            )
        )
        and "OperationalEventEmitter" in route_source,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1378",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "source_count": payload.get("summary", {}).get("source_count", 0),
            "stage_count": payload.get("summary", {}).get("stage_count", 0),
            "audit_event_count": len(events),
        },
        "decision": {
            "new_table_required": False,
            "database_required": False,
            "remote_provider_required": False,
            "postgres_evidence_slice": "1380",
            "next_slice": "1379" if passed else "blocked",
        },
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


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
        "ag_cross_service_trace_operations_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"sources={summary.get('source_count', 0)} "
        f"stages={summary.get('stage_count', 0)} "
        f"audit={summary.get('audit_event_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ag_cross_service_trace_operations_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
