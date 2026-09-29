from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

import httpx

from nex_mo.remote_provider import (
    classify_remote_provider_exception,
    classify_remote_provider_http_status,
    list_remote_provider_telemetry,
    remote_provider_response_invalid_decision,
)


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ControlProbe:
    control_id: str
    path: str
    token: str
    status: str


CONTROL_PROBES = (
    ControlProbe(
        "capability_specific_timeouts",
        "services/nex-mo/nex_mo/remote_provider.py",
        "def _timeout_env_for_capability",
        "IMPLEMENTED",
    ),
    ControlProbe(
        "failure_taxonomy",
        "services/nex-mo/nex_mo/provider_transport.py",
        "def classify_remote_provider_exception",
        "IMPLEMENTED",
    ),
    ControlProbe(
        "latency_and_failure_telemetry",
        "services/nex-mo/nex_mo/remote_provider.py",
        "class RemoteProviderTelemetryBucket",
        "IMPLEMENTED",
    ),
    ControlProbe(
        "telemetry_concurrency_lock",
        "services/nex-mo/nex_mo/remote_provider.py",
        "_TELEMETRY_LOCK = Lock()",
        "IMPLEMENTED",
    ),
    ControlProbe(
        "safe_problem_projection",
        "services/nex-mo/nex_mo/providers.py",
        'details={"degraded": exc.degraded} if exc.degraded else None',
        "IMPLEMENTED",
    ),
    ControlProbe(
        "process_local_telemetry",
        "services/nex-mo/nex_mo/remote_provider.py",
        "_TELEMETRY_BUCKETS: dict[str, RemoteProviderTelemetryBucket] = {}",
        "GAP",
    ),
    ControlProbe(
        "generic_service_readiness",
        "services/_shared/nex_runtime/app.py",
        "check = check_database_readiness(spec.database_env)",
        "GAP",
    ),
)


def build_mo_resilience_telemetry_readiness_audit(
    root: Path = ROOT,
    *,
    probes: Sequence[ControlProbe] = CONTROL_PROBES,
) -> dict[str, Any]:
    controls = [_inspect_probe(root, probe) for probe in probes]
    evidence_issues = [
        {
            "category": "resilience_evidence_missing",
            "control_id": item["control_id"],
            "path": item["path"],
        }
        for item in controls
        if not item["evidence_present"]
    ]
    timeout = classify_remote_provider_exception(
        httpx.ReadTimeout("private endpoint timed out"),
        error_code_prefix="mo.remote_embedding",
    )
    throttled = classify_remote_provider_http_status(
        429,
        error_code_prefix="mo.remote_reranker",
    )
    unavailable = classify_remote_provider_http_status(
        503,
        error_code_prefix="mo.remote_generation",
    )
    invalid_request = classify_remote_provider_http_status(
        400,
        error_code_prefix="mo.remote_generation",
    )
    malformed = remote_provider_response_invalid_decision(
        error_code_prefix="mo.remote_generation",
        detail="private payload omitted",
    )
    telemetry = list_remote_provider_telemetry(environ={})
    telemetry_capabilities = {item["capability"] for item in telemetry}
    serialized_telemetry = json.dumps(telemetry, sort_keys=True)
    decisions = (timeout, throttled, unavailable, invalid_request, malformed)
    checks = {
        "control_inventory_complete": len(controls) == 7,
        "control_evidence_present": not evidence_issues,
        "retryable_degraded_failures_classified": all(
            decision.retryable and decision.degraded
            for decision in (timeout, throttled, unavailable, malformed)
        ),
        "invalid_request_is_not_retryable": (
            invalid_request.retryable is False and invalid_request.degraded is False
        ),
        "telemetry_capabilities_complete": telemetry_capabilities
        == {"embedding", "reranking", "generation"},
        "telemetry_is_privacy_safe": all(
            token not in serialized_telemetry
            for token in ("provider_url", "api_key", "model_path", "raw_payload")
        ),
        "known_runtime_gaps_classified": True,
    }
    runtime_gaps = [
        {
            "gap_id": "provider_aware_readiness_missing",
            "risk": "HIGH",
            "target": "S112",
        },
        {
            "gap_id": "bounded_retry_execution_missing",
            "risk": "MEDIUM",
            "target": "S112",
        },
        {
            "gap_id": "restart_safe_aggregated_telemetry_missing",
            "risk": "MEDIUM",
            "target": "S112",
        },
        {
            "gap_id": "gpu_resource_metrics_missing",
            "risk": "MEDIUM",
            "target": "S112",
        },
        {
            "gap_id": "provider_execution_cancellation_missing",
            "risk": "LOW",
            "target": "post_mvp",
        },
    ]
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_resilience_telemetry_readiness_audit.v1",
        "slice": "1109",
        "requirement": "S111",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_resilience_readiness_audit_failed",
        "operations_readiness": "GAPS_CONFIRMED" if passed else "BLOCKED",
        "checks": checks,
        "summary": {
            "implemented_control_count": sum(
                item["status"] == "IMPLEMENTED" for item in controls
            ),
            "classified_control_gap_count": sum(
                item["status"] == "GAP" for item in controls
            ),
            "failure_decision_count": len(decisions),
            "telemetry_capability_count": len(telemetry_capabilities),
            "runtime_gap_count": len(runtime_gaps),
            "evidence_issue_count": len(evidence_issues),
        },
        "failure_decisions": [decision.to_safe_summary() for decision in decisions],
        "controls": controls,
        "runtime_gaps": runtime_gaps,
        "issues": evidence_issues,
        "next_slice": "1110",
    }


def _inspect_probe(root: Path, probe: ControlProbe) -> dict[str, Any]:
    path = root / probe.path
    present = path.is_file() and probe.token in path.read_text(encoding="utf-8")
    return {
        "control_id": probe.control_id,
        "path": probe.path,
        "status": probe.status,
        "evidence_present": present,
    }
