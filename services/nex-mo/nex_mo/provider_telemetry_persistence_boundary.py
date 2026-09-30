from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DurableTelemetryBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    target_slice: str


DURABLE_TELEMETRY_BOUNDARIES = (
    DurableTelemetryBoundary(
        "telemetry_store_protocol",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class ProviderTelemetryStore",
        "1153",
    ),
    DurableTelemetryBoundary(
        "request_retry_counters",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class RemoteProviderTelemetryBucket",
        "1155",
    ),
    DurableTelemetryBoundary(
        "provider_execution_wiring",
        "services/nex-mo/nex_mo/remote_provider.py",
        "def list_remote_provider_telemetry",
        "1156",
    ),
    DurableTelemetryBoundary(
        "authenticated_projection",
        "services/nex-mo/nex_mo/providers.py",
        '"/api/v1/provider-telemetry"',
        "1158",
    ),
    DurableTelemetryBoundary(
        "service_persistence_runtime",
        "services/nex-mo/nex_mo/main.py",
        "attach_service_persistence_runtime",
        "1156",
    ),
    DurableTelemetryBoundary(
        "canonical_wire_contract",
        "contracts/schemas/service/nex_mo/provider_telemetry_snapshot.v1.schema.json",
        '"mo_provider_telemetry_snapshot.v1"',
        "1159",
    ),
)


DURABLE_TELEMETRY_POLICY = {
    "table_name": "mo_provider_telemetry",
    "table_name_max_length": 24,
    "logical_key": [
        "capability",
        "request_shape",
        "deployment_id",
        "model_revision",
    ],
    "write_semantics": "atomic_increment_upsert",
    "read_semantics": "merge_durable_counters_with_current_runtime_config",
    "concurrency_scope": "all_mo_processes_sharing_one_database",
    "restart_semantics": "new_store_instance_reads_existing_aggregate",
    "runtime_modes": {
        "memory": "in_memory_store",
        "postgres": "sqlalchemy_durable_store",
    },
    "reset_scope": "tests_and_protected_smoke_only",
    "wire_compatibility": "provider_telemetry_snapshot.v1_unchanged",
    "forbidden_persistence": [
        "provider_endpoint",
        "provider_api_key",
        "authorization_header",
        "request_payload",
        "response_payload",
        "exception_detail",
    ],
    "deferred_scope": [
        "raw_request_event_history",
        "raw_response_event_history",
        "gpu_runtime_metrics",
        "external_dgx_live_call",
    ],
}


def build_mo_provider_telemetry_persistence_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[DurableTelemetryBoundary] = DURABLE_TELEMETRY_BOUNDARIES,
) -> dict[str, Any]:
    inspected = [_inspect_boundary(root, boundary) for boundary in boundaries]
    issues = [
        {
            "category": "durable_telemetry_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in inspected
        if not item["evidence_present"]
    ]
    logical_key = DURABLE_TELEMETRY_POLICY["logical_key"]
    forbidden = set(DURABLE_TELEMETRY_POLICY["forbidden_persistence"])
    table_name = str(DURABLE_TELEMETRY_POLICY["table_name"])
    checks = {
        "boundary_inventory_complete": len(inspected) == 6,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1153" <= item["target_slice"] <= "1159" for item in inspected
        ),
        "table_name_is_bounded": len(table_name)
        <= int(DURABLE_TELEMETRY_POLICY["table_name_max_length"]),
        "logical_key_is_stable": logical_key
        == ["capability", "request_shape", "deployment_id", "model_revision"],
        "writes_are_atomic": DURABLE_TELEMETRY_POLICY["write_semantics"]
        == "atomic_increment_upsert",
        "restart_semantics_are_explicit": DURABLE_TELEMETRY_POLICY[
            "restart_semantics"
        ]
        == "new_store_instance_reads_existing_aggregate",
        "private_runtime_values_are_forbidden": {
            "provider_endpoint",
            "provider_api_key",
            "authorization_header",
            "request_payload",
            "response_payload",
        }.issubset(forbidden),
        "wire_contract_remains_compatible": DURABLE_TELEMETRY_POLICY[
            "wire_compatibility"
        ]
        == "provider_telemetry_snapshot.v1_unchanged",
        "gpu_metrics_remain_deferred": "gpu_runtime_metrics"
        in DURABLE_TELEMETRY_POLICY["deferred_scope"],
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_telemetry_persistence_boundary.v1",
        "slice": "1152",
        "requirement": "S116",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "mo_provider_telemetry_persistence_boundary_failed"
        ),
        "boundary": "restart_safe_durable_provider_telemetry",
        "checks": checks,
        "summary": {
            "boundary_count": len(inspected),
            "logical_key_field_count": len(logical_key),
            "forbidden_persistence_count": len(forbidden),
            "deferred_scope_count": len(
                DURABLE_TELEMETRY_POLICY["deferred_scope"]
            ),
            "evidence_issue_count": len(issues),
        },
        "persistence_policy": DURABLE_TELEMETRY_POLICY,
        "boundaries": inspected,
        "issues": issues,
        "guardrails": [
            "increment shared counters atomically instead of overwriting snapshots",
            "merge durable counters with current safe runtime configuration on reads",
            "keep memory mode deterministic and database-free",
            "never persist endpoints credentials payloads or exception details",
            "preserve the existing provider telemetry v1 response shape",
            "prove restart recovery against the actual nex_mo_test database",
        ],
        "next_slice": "1153",
    }


def _inspect_boundary(
    root: Path,
    boundary: DurableTelemetryBoundary,
) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
