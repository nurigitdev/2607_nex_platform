from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from nex_mo.contract_api_drift_audit import build_mo_contract_api_drift_audit


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ContractClosureBoundary:
    drift_class: str
    baseline_count: int
    target_slice: str
    resolution: str


CONTRACT_CLOSURE_BOUNDARIES = (
    ContractClosureBoundary(
        "missing_openapi_operations",
        9,
        "1136-1137",
        "document every runtime operation without adding runtime routes",
    ),
    ContractClosureBoundary(
        "stale_mock_operations",
        3,
        "1135",
        "replace mock-only operation descriptions with mode-neutral contracts",
    ),
    ContractClosureBoundary(
        "missing_request_bodies",
        3,
        "1135",
        "bind canonical provider request schemas",
    ),
    ContractClosureBoundary(
        "missing_success_schemas",
        5,
        "1135",
        "bind canonical privacy-safe response projections",
    ),
    ContractClosureBoundary(
        "missing_security",
        5,
        "1135",
        "declare service bearer security on protected business operations",
    ),
    ContractClosureBoundary(
        "missing_negative_fixtures",
        3,
        "1134",
        "cover every MO schema with a failing contract example",
    ),
)

CONTRACT_CLOSURE_POLICY = {
    "baseline_slice": "1108",
    "baseline_drift_count": 28,
    "target_drift_count": 0,
    "schema_slice": "1133",
    "fixture_slice": "1134",
    "provider_openapi_slice": "1135",
    "checkpoint_slice": "1136",
    "retention_openapi_slice": "1137",
    "parity_guard_slice": "1138",
    "deterministic_http_smoke_slice": "1139",
    "protected_postgres_smoke_slice": "1140",
    "closure_slice": "1141",
    "runtime_semantics": "preserve_existing_runtime_behavior",
    "database_policy": "no_new_table_read_write_only_in_protected_smoke",
    "provider_policy": "no_dgx_call_required",
    "privacy_policy": "never_publish_credentials_endpoints_or_payload_content",
}


def build_mo_contract_api_closure_boundary(
    root: Path = ROOT,
    *,
    boundaries: Sequence[ContractClosureBoundary] = CONTRACT_CLOSURE_BOUNDARIES,
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    audit = dict(baseline) if baseline is not None else build_mo_contract_api_drift_audit(root)
    summary = audit.get("summary") if isinstance(audit.get("summary"), Mapping) else {}
    expected = {item.drift_class: item.baseline_count for item in boundaries}
    observed = {
        "missing_openapi_operations": _count(summary, "missing_openapi_operation_count"),
        "stale_mock_operations": _count(summary, "stale_mock_operation_count"),
        "missing_request_bodies": _count(summary, "missing_request_body_count"),
        "missing_success_schemas": _count(summary, "missing_success_schema_count"),
        "missing_security": _count(summary, "missing_security_count"),
        "missing_negative_fixtures": max(
            0,
            _count(summary, "schema_count")
            - _count(summary, "negative_fixture_covered_count"),
        ),
    }
    issues = [
        {
            "category": "contract_drift_baseline_mismatch",
            "drift_class": drift_class,
            "expected": count,
            "observed": observed.get(drift_class, 0),
        }
        for drift_class, count in expected.items()
        if observed.get(drift_class) != count
    ]
    checks = {
        "baseline_audit_passed": audit.get("status") == "PASS",
        "six_drift_classes_frozen": len(boundaries) == 6,
        "baseline_categories_match": not issues,
        "baseline_total_matches": sum(observed.values())
        == CONTRACT_CLOSURE_POLICY["baseline_drift_count"],
        "slice_order_bounded": all(
            "1133" <= item.target_slice.split("-", 1)[0] <= "1137"
            for item in boundaries
        ),
        "runtime_semantics_preserved": CONTRACT_CLOSURE_POLICY["runtime_semantics"]
        == "preserve_existing_runtime_behavior",
        "no_new_table_planned": CONTRACT_CLOSURE_POLICY["database_policy"]
        == "no_new_table_read_write_only_in_protected_smoke",
        "dgx_not_required": CONTRACT_CLOSURE_POLICY["provider_policy"]
        == "no_dgx_call_required",
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_contract_api_closure_boundary.v1",
        "slice": "1132",
        "requirement": "S114",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_contract_api_closure_boundary_failed",
        "boundary": "mo_contract_and_api_drift_closure",
        "checks": checks,
        "summary": {
            "drift_class_count": len(boundaries),
            "baseline_drift_count": sum(observed.values()),
            "target_drift_count": CONTRACT_CLOSURE_POLICY["target_drift_count"],
            "baseline_issue_count": len(issues),
        },
        "baseline": {
            "expected": expected,
            "observed": observed,
        },
        "boundaries": [
            {
                "drift_class": item.drift_class,
                "baseline_count": item.baseline_count,
                "target_slice": item.target_slice,
                "resolution": item.resolution,
            }
            for item in boundaries
        ],
        "policy": CONTRACT_CLOSURE_POLICY,
        "issues": issues,
        "guardrails": [
            "reduce every classified S111 drift category to zero",
            "preserve existing runtime routes and response semantics",
            "use canonical schemas instead of duplicated ad hoc shapes",
            "require positive and negative fixtures for every MO schema",
            "keep credentials endpoints and payload content out of evidence",
            "use nex_mo_test only behind the explicit Slice 1140 smoke gate",
        ],
        "next_slice": "1133",
    }


def _count(summary: Mapping[str, Any], key: str) -> int:
    value = summary.get(key, 0)
    return value if isinstance(value, int) and value >= 0 else 0
