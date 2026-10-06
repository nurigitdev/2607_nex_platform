#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-ag"):
    sys.path.insert(0, str(path))

from nex_ag.cross_service_trace import (  # noqa: E402
    AG_TRACE_REQUIRED_SCOPES,
    AG_TRACE_SOURCE_PATH,
    AgTraceSourceError,
    CrossServiceTraceAggregator,
)
from nex_runtime import (  # noqa: E402
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
)

SCHEMA_VERSION = "ag_cross_service_trace_aggregation_contract_evidence.v1"
TRACE_ID = "13771377137713771377137713771377"
REQUEST_TRACE_ID = "77137713771377137713771377137713"


class _SourceClient:
    def __init__(self, service_id: str, result: object) -> None:
        self.service_id = service_id
        self._result = result

    def get_trace_projection(
        self,
        trace_id: str,
        *,
        request_id: str,
        request_trace_id: str,
    ) -> dict[str, Any]:
        del trace_id, request_id, request_trace_id
        if isinstance(self._result, Exception):
            raise self._result
        return self._result  # type: ignore[return-value]


def run_ag_cross_service_trace_aggregation_contract(
    root: Path = ROOT,
) -> dict[str, Any]:
    sources = {
        "nex-oa": _SourceClient(
            "nex-oa",
            _projection(
                "nex-oa",
                "AUTH",
                "2026-10-06T13:00:00Z",
                {"result_code": "AUTHENTICATED"},
            ),
        ),
        "nex-ae-api": _SourceClient(
            "nex-ae-api",
            AgTraceSourceError(
                "nex-ae-api",
                "ag.trace_source_timeout",
                "UNAVAILABLE",
                retryable=True,
            ),
        ),
        "nex-cx": _SourceClient(
            "nex-cx",
            _projection(
                "nex-cx",
                "GENERATION",
                "2026-10-06T13:02:00Z",
                {"citation_status": "VALIDATED", "attempt": 1},
            ),
        ),
        "nex-mo": _SourceClient(
            "nex-mo",
            _projection(
                "nex-mo",
                "GENERATION",
                "2026-10-06T13:01:00Z",
                {
                    "provider_capability": "generation",
                    "model_alias": "general-llm-default",
                    "model_revision": "model-revision",
                    "deployment_id": "deployment-1377",
                    "provider_route_id": "route-1377",
                    "provider_mode": "live",
                },
            ),
        ),
    }
    result = CrossServiceTraceAggregator(
        sources,
        clock=lambda: datetime(2026, 10, 6, 13, 3, tzinfo=UTC),
    ).aggregate(
        TRACE_ID,
        request_id="request-1377",
        request_trace_id=REQUEST_TRACE_ID,
    )
    schema = _load_json(
        root / "contracts/schemas/service/nex_ag/cross_service_trace_e2e.v1.schema.json"
    )
    source = _read_text(root / "services/nex-ag/nex_ag/cross_service_trace.py")
    serialized = json.dumps(
        {"projection": result.projection, "diagnostics": result.diagnostics},
        sort_keys=True,
    )
    source_statuses = {
        item["service_id"]: item["source_status"]
        for item in result.projection["source_statuses"]
    }
    checks = {
        "timeline_contract_valid": _validates(schema, result.projection),
        "four_sources_registered": tuple(sources)
        == ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo"),
        "operations_scopes_required": AG_TRACE_REQUIRED_SCOPES
        == ("service:call", "operations:read"),
        "canonical_internal_path_used": AG_TRACE_SOURCE_PATH
        == "/internal/v1/operations/traces/{trace_id}",
        "partial_failure_explicit": source_statuses["nex-ae-api"] == "UNAVAILABLE"
        and result.projection["projection_status"] == "DEGRADED",
        "healthy_sources_preserved": all(
            source_statuses[service_id] == "READY"
            for service_id in ("nex-oa", "nex-cx", "nex-mo")
        ),
        "timeline_sorted": [
            stage["service_id"] for stage in result.projection["timeline"]
        ]
        == ["nex-oa", "nex-mo", "nex-cx"],
        "model_identity_is_alias_based": all(
            key in result.projection["timeline"][1]["safe_attributes"]
            for key in (
                "model_alias",
                "model_revision",
                "deployment_id",
                "provider_route_id",
            )
        ),
        "diagnostics_are_metadata_only": result.diagnostics
        == (
            {
                "service_id": "nex-ae-api",
                "error_code": "ag.trace_source_timeout",
                "retryable": True,
                "status_code": 503,
            },
        ),
        "private_payload_absent": all(
            token not in serialized
            for token in (
                "prompt",
                "generated_text",
                "provider_url",
                "database_url",
                "storage_ref",
            )
        ),
        "database_adapter_not_imported": "sqlalchemy" not in source.lower()
        and "database_url" not in source.lower(),
        "strict_source_validation_present": (
            "validate_cross_service_trace_source_projection" in source
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1377",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, value in checks.items() if not value],
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "source_count": len(source_statuses),
            "ready_source_count": sum(
                status == "READY" for status in source_statuses.values()
            ),
            "stage_count": len(result.projection["timeline"]),
            "diagnostic_count": len(result.diagnostics),
        },
        "decision": {
            "legacy_database_reads_allowed": False,
            "database_required": False,
            "remote_provider_required": False,
            "route_wiring_slice": "1378",
            "next_slice": "1378" if passed else "blocked",
        },
    }


def _projection(
    service_id: str,
    stage_family: str,
    timestamp: str,
    safe_attributes: Mapping[str, object],
) -> dict[str, Any]:
    stage = build_cross_service_trace_stage(
        stage_id=f"stage-{service_id}-1377",
        trace_id=TRACE_ID,
        request_id=f"request-{service_id}-1377",
        service_id=service_id,
        stage_family=stage_family,
        stage_status="SUCCEEDED",
        operation_timestamp=timestamp,
        safe_attributes=safe_attributes,
    )
    return build_cross_service_trace_source_projection(
        service_id=service_id,
        trace_id=TRACE_ID,
        stages=[stage],
        source_status="READY",
        checked_at="2026-10-06T13:03:00Z",
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ag_cross_service_trace_aggregation_contract="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"sources={summary.get('ready_source_count', 0)}/"
        f"{summary.get('source_count', 0)} "
        f"stages={summary.get('stage_count', 0)} "
        f"diagnostics={summary.get('diagnostic_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ag_cross_service_trace_aggregation_contract()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
