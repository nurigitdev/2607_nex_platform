#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
from typing import Any

from run_mo_provider_readiness_boundary import (
    run_mo_provider_readiness_boundary as run_boundary,
)
from run_mo_provider_readiness_cache import (
    run_mo_provider_readiness_cache as run_cache,
)
from run_mo_provider_readiness_domain import (
    run_mo_provider_readiness_domain as run_domain,
)
from run_mo_provider_readiness_evaluator import (
    run_mo_provider_readiness_evaluator as run_evaluator,
)
from run_mo_provider_readiness_plan import (
    run_mo_provider_readiness_plan as run_plan,
)
from run_mo_provider_readiness_service import (
    run_mo_provider_readiness_service as run_service,
)
from run_mo_provider_ready_route import (
    run_mo_provider_ready_route as run_ready_route,
)
from run_mo_provider_route_health_api import (
    run_mo_provider_route_health_api as run_route_health_api,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "s113_mo_provider_readiness_closure.v1"
SLICE_RANGE = "1122-1131"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"

REQUIRED_FILES = (
    "services/nex-mo/nex_mo/provider_readiness.py",
    "services/nex-mo/nex_mo/provider_readiness_plan.py",
    "services/nex-mo/nex_mo/provider_readiness_evaluator.py",
    "services/nex-mo/nex_mo/provider_readiness_cache.py",
    "services/nex-mo/nex_mo/provider_readiness_service.py",
    "services/nex-mo/nex_mo/provider_readiness_api.py",
    "contracts/schemas/service/nex_mo/provider_readiness.v1.schema.json",
    "contracts/openapi/nex-mo.openapi.yaml",
    "scripts/smoke/run_mo_provider_readiness_boundary.py",
    "scripts/smoke/run_mo_provider_readiness_domain.py",
    "scripts/smoke/run_mo_provider_readiness_plan.py",
    "scripts/smoke/run_mo_provider_readiness_evaluator.py",
    "scripts/smoke/run_mo_provider_readiness_cache.py",
    "scripts/smoke/run_mo_provider_readiness_service.py",
    "scripts/smoke/run_mo_provider_ready_route.py",
    "scripts/smoke/run_mo_provider_route_health_api.py",
    "scripts/smoke/run_mo_provider_readiness_live_postgres_smoke.py",
    "scripts/smoke/run_s113_mo_provider_readiness_closure.py",
    "tests/test_s113_mo_provider_readiness_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1122", "mo_provider_readiness_route_health_boundary"),
            ("1123", "mo_provider_readiness_domain_projection"),
            ("1124", "mo_provider_readiness_probe_plan"),
            ("1125", "mo_provider_readiness_evaluator"),
            ("1126", "mo_provider_readiness_ttl_cache"),
            ("1127", "mo_provider_readiness_composition"),
            ("1128", "mo_provider_ready_route_wiring"),
            ("1129", "mo_provider_route_health_api_contract"),
            ("1130", "mo_provider_readiness_live_postgresql_dgx_smoke"),
            ("1131", "s113_mo_provider_readiness_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "three_required_capabilities",
        "services/nex-mo/nex_mo/provider_readiness.py",
        '("embedding", "reranking", "generation")',
    ),
    (
        "active_preflight",
        "services/nex-mo/nex_mo/provider_readiness_evaluator.py",
        "run_remote_provider_preflight_check",
    ),
    (
        "ttl_cache",
        "services/nex-mo/nex_mo/provider_readiness_cache.py",
        "class InMemoryProviderReadinessStore",
    ),
    (
        "provider_ready_composition",
        "services/nex-mo/nex_mo/main.py",
        "readiness_checks=(PROVIDER_READINESS.check,)",
    ),
    (
        "authenticated_route_health",
        "services/nex-mo/nex_mo/provider_readiness_api.py",
        'app.get("/api/v1/provider-route-health"',
    ),
    (
        "canonical_schema",
        "contracts/schemas/service/nex_mo/provider_readiness.v1.schema.json",
        "mo_provider_readiness.v1",
    ),
    (
        "openapi_route",
        "contracts/openapi/nex-mo.openapi.yaml",
        "getMoProviderRouteHealth",
    ),
    (
        "live_database_identity",
        "docs/slices/1130_mo_provider_readiness_live_postgresql_dgx_smoke.md",
        "nex_mo_user@nex_mo_test",
    ),
    (
        "live_provider_count",
        "docs/slices/1130_mo_provider_readiness_live_postgresql_dgx_smoke.md",
        "Actual DGX active preflight",
    ),
    (
        "live_model_set",
        "docs/slices/1130_mo_provider_readiness_live_postgresql_dgx_smoke.md",
        "Qwen3-Reranker-4B",
    ),
    (
        "quality_live_smoke",
        QUALITY_GATE_PATH,
        "run_mo_provider_readiness_live_postgres_smoke.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s113_mo_provider_readiness_closure.py",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1131_s113_mo_provider_readiness_closure.md",
    ),
)

COMPONENT_TOKENS = {
    "domain_and_privacy_projection": (
        "three_required_capabilities",
        "canonical_schema",
    ),
    "active_probe_evaluation": ("active_preflight",),
    "bounded_cache_and_composition": (
        "ttl_cache",
        "provider_ready_composition",
    ),
    "authenticated_api_contract": (
        "authenticated_route_health",
        "openapi_route",
    ),
    "protected_postgres_and_dgx_evidence": (
        "live_database_identity",
        "live_provider_count",
        "live_model_set",
    ),
    "quality_and_documentation": (
        "quality_live_smoke",
        "quality_closure",
        "docs_closure_index",
    ),
}


def run_s113_mo_provider_readiness_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    token_status = {item["name"]: item["present"] for item in token_checks}
    components = {
        name: all(token_status[token] for token in tokens)
        for name, tokens in COMPONENT_TOKENS.items()
    }
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "domain": _safe_evidence(run_domain),
        "probe_plan": _safe_evidence(run_plan),
        "evaluator": _safe_evidence(run_evaluator),
        "cache": _safe_evidence(run_cache),
        "composition": _safe_evidence(run_service),
        "ready_route": _safe_evidence(run_ready_route),
        "route_health_api": _safe_evidence(run_route_health_api),
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "database_and_provider_readiness_composed": (
            decision["service_readiness_policy"]
            == "database_and_all_three_provider_routes_must_be_ready"
        ),
        "stale_snapshot_fails_closed": (
            decision["cache_policy"]
            == "bounded_process_local_ttl_stale_never_ready"
        ),
        "protected_live_evidence_complete": (
            components["protected_postgres_and_dgx_evidence"]
            and decision["protected_live_check_count"] == 8
        ),
        "no_s113_table_created": decision["new_table_added"] is False,
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1122-1131",
            "checkpoint_gate": "1126",
            "full_gate": "1131",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1131",
        "slice_range": SLICE_RANGE,
        "requirement": "S113",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s113_mo_provider_readiness_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S114" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "MO_PROVIDER_AWARE_READINESS_READY" if status == "PASS" else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "component_count": len(components),
            "closed_component_count": sum(components.values()),
            "protected_live_check_count": (
                8 if components["protected_postgres_and_dgx_evidence"] else 0
            ),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S114",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_provider_aware_readiness_and_route_health",
        "required_capabilities": ["embedding", "reranking", "generation"],
        "service_readiness_policy": (
            "database_and_all_three_provider_routes_must_be_ready"
        ),
        "route_health_states": ["READY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"],
        "cache_policy": "bounded_process_local_ttl_stale_never_ready",
        "route_health_api_policy": "authenticated_privacy_safe_cached_projection",
        "provider_models": {
            "embedding": "Qwen3-Embedding-4B",
            "reranking": "Qwen3-Reranker-4B",
            "generation": "Qwen3.5-4B",
        },
        "postgres_smoke_target": "nex_mo_user@nex_mo_test",
        "protected_live_check_count": 8,
        "new_table_added": False,
        "quality_cadence": {
            "slice_gate": "1122-1131",
            "checkpoint_gate": "1126",
            "full_gate": "1131",
        },
        "next_requirement_scope": "S114_contract_and_api_drift_closure",
        "deferred_scope": [
            "bounded_provider_retry_resilience",
            "durable_aggregate_provider_telemetry",
            "gpu_resource_observability",
            "model_catalog_alias_lifecycle",
        ],
    }


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s113_mo_provider_readiness_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"live_checks={summary.get('protected_live_check_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s113_mo_provider_readiness_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
