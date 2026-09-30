from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ResilienceBoundary:
    boundary_id: str
    source_path: str
    evidence_token: str
    target_slice: str


RESILIENCE_BOUNDARIES = (
    ResilienceBoundary(
        "remote_transport",
        "services/nex-mo/nex_mo/provider_transport.py",
        "def execute_remote_json_request",
        "1144",
    ),
    ResilienceBoundary(
        "failure_taxonomy",
        "services/nex-mo/nex_mo/provider_transport.py",
        "class RemoteProviderFailureDecision",
        "1143",
    ),
    ResilienceBoundary(
        "execution_configuration",
        "services/nex-mo/nex_mo/remote_provider.py",
        "class RemoteProviderExecutionConfig",
        "1145",
    ),
    ResilienceBoundary(
        "attempt_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        "class ProviderTelemetryStore",
        "1147",
    ),
    ResilienceBoundary(
        "readiness_composition",
        "services/nex-mo/nex_mo/provider_readiness_service.py",
        "class ProviderReadinessService",
        "1148",
    ),
    ResilienceBoundary(
        "provider_api_contract",
        "contracts/openapi/nex-mo.openapi.yaml",
        "getMoProviderTelemetry",
        "1150",
    ),
)

RESILIENCE_POLICY = {
    "attempt_limits": {"embedding": 3, "reranking": 3, "generation": 2},
    "retryable_failure_kinds": [
        "connect_timeout",
        "connection_error",
        "throttled",
        "upstream_5xx",
    ],
    "generation_ambiguous_no_retry": [
        "read_timeout",
        "write_timeout",
        "malformed_response",
    ],
    "backoff": "bounded_exponential_full_jitter_with_injected_sources",
    "retry_after": "honor_delta_seconds_with_policy_cap",
    "budget_scope": "single_provider_request_only",
    "persistence": "process_local_no_table_in_s115",
    "durable_telemetry_requirement": "S116",
    "gpu_runtime_observability_requirement": "S117",
    "forbidden_projection": [
        "provider_endpoint",
        "provider_api_key",
        "authorization_header",
        "request_payload",
        "response_payload",
        "exception_detail",
    ],
}


def build_mo_provider_resilience_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[ResilienceBoundary] = RESILIENCE_BOUNDARIES,
) -> dict[str, Any]:
    results = [_inspect_boundary(root, item) for item in boundaries]
    issues = [
        {
            "category": "resilience_boundary_evidence_missing",
            "boundary_id": item["boundary_id"],
            "source_path": item["source_path"],
        }
        for item in results
        if not item["evidence_present"]
    ]
    attempts = RESILIENCE_POLICY["attempt_limits"]
    forbidden = set(RESILIENCE_POLICY["forbidden_projection"])
    checks = {
        "boundary_inventory_complete": len(results) == 6,
        "source_evidence_present": not issues,
        "slice_order_bounded": all(
            "1143" <= item["target_slice"] <= "1150" for item in results
        ),
        "capability_attempt_limits_bounded": attempts
        == {"embedding": 3, "reranking": 3, "generation": 2},
        "generation_policy_is_conservative": set(
            RESILIENCE_POLICY["generation_ambiguous_no_retry"]
        )
        == {"read_timeout", "write_timeout", "malformed_response"},
        "backoff_is_bounded_and_testable": RESILIENCE_POLICY["backoff"]
        == "bounded_exponential_full_jitter_with_injected_sources",
        "private_runtime_values_forbidden": {
            "provider_endpoint",
            "provider_api_key",
            "authorization_header",
            "request_payload",
            "response_payload",
        }.issubset(forbidden),
        "scope_defers_durable_and_gpu_work": (
            RESILIENCE_POLICY["persistence"] == "process_local_no_table_in_s115"
            and RESILIENCE_POLICY["durable_telemetry_requirement"] == "S116"
            and RESILIENCE_POLICY["gpu_runtime_observability_requirement"] == "S117"
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_resilience_boundary.v1",
        "slice": "1142",
        "requirement": "S115",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_resilience_boundary_failed",
        "boundary": "provider_request_bounded_retry_and_resilience",
        "checks": checks,
        "summary": {
            "boundary_count": len(results),
            "capability_count": len(attempts),
            "retryable_failure_kind_count": len(
                RESILIENCE_POLICY["retryable_failure_kinds"]
            ),
            "forbidden_projection_count": len(forbidden),
            "evidence_issue_count": len(issues),
        },
        "resilience_policy": RESILIENCE_POLICY,
        "boundaries": results,
        "issues": issues,
        "guardrails": [
            "keep retry execution bounded to one logical provider request",
            "never retry non-retryable upstream 4xx or invalid local requests",
            "avoid ambiguous generation replay after a response may have started",
            "inject sleeper clock and jitter sources for deterministic tests",
            "never project endpoints credentials payloads or exception details",
            "do not add durable telemetry tables or GPU metrics in S115",
        ],
        "next_slice": "1143",
    }


def _inspect_boundary(root: Path, boundary: ResilienceBoundary) -> dict[str, Any]:
    path = root / boundary.source_path
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    return {
        "boundary_id": boundary.boundary_id,
        "source_path": boundary.source_path,
        "target_slice": boundary.target_slice,
        "evidence_present": boundary.evidence_token in source,
    }
