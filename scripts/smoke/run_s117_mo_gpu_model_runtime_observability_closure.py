#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from run_mo_runtime_observability_api import (  # noqa: E402
    run_mo_runtime_observability_api as run_api,
)
from run_mo_runtime_observability_boundary import (  # noqa: E402
    run_mo_runtime_observability_boundary as run_boundary,
)
from run_mo_runtime_observability_contract import (  # noqa: E402
    run_mo_runtime_observability_contract as run_contract,
)
from run_mo_runtime_observability_domain import (  # noqa: E402
    run_mo_runtime_observability_domain as run_domain,
)
from run_mo_runtime_observability_policy import (  # noqa: E402
    run_mo_runtime_observability_policy as run_policy,
)
from run_mo_runtime_observability_service import (  # noqa: E402
    run_mo_runtime_observability_service as run_service,
)
from run_mo_runtime_observation_collector import (  # noqa: E402
    run_mo_runtime_observation_collector as run_collector,
)
from run_mo_runtime_observation_plan import (  # noqa: E402
    run_mo_runtime_observation_plan as run_plan,
)


SCHEMA_VERSION = "s117_mo_gpu_model_runtime_observability_closure.v1"
SLICE_RANGE = "1162-1171"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
LIVE_DOCUMENT = "docs/slices/1170_mo_runtime_observability_dgx_live_evidence.md"
QUALITY_SCRIPTS = (
    "run_mo_runtime_observability_boundary.py",
    "run_mo_runtime_observability_domain.py",
    "run_mo_runtime_observation_plan.py",
    "run_mo_runtime_observation_collector.py",
    "run_mo_runtime_observability_service.py",
    "run_mo_runtime_observability_api.py",
    "run_mo_runtime_observability_policy.py",
    "run_mo_runtime_observability_contract.py",
    "run_mo_runtime_observability_live_smoke.py",
    "run_s117_mo_gpu_model_runtime_observability_closure.py",
)
SLICE_DOCUMENTS = (
    "1162_mo_gpu_model_runtime_observability_boundary.md",
    "1163_mo_runtime_observation_domain_projection.md",
    "1164_mo_protected_runtime_collector_plan.md",
    "1165_mo_gpu_model_runtime_collector_normalization.md",
    "1166_mo_runtime_observability_ttl_service.md",
    "1167_mo_authenticated_runtime_observability_api.md",
    "1168_mo_runtime_observability_status_policy.md",
    "1169_mo_runtime_observability_contract_hardening.md",
    "1170_mo_runtime_observability_dgx_live_evidence.md",
    "1171_s117_mo_gpu_model_runtime_observability_closure.md",
)
REQUIRED_FILES = (
    "services/nex-mo/nex_mo/runtime_observability_boundary.py",
    "services/nex-mo/nex_mo/runtime_observability.py",
    "services/nex-mo/nex_mo/runtime_observability_plan.py",
    "services/nex-mo/nex_mo/runtime_observability_collector.py",
    "services/nex-mo/nex_mo/runtime_observability_cache.py",
    "services/nex-mo/nex_mo/runtime_observability_service.py",
    "services/nex-mo/nex_mo/runtime_observability_api.py",
    "services/nex-mo/nex_mo/runtime_observability_policy.py",
    "services/nex-mo/nex_mo/runtime_observability_contract.py",
    "contracts/schemas/service/nex_mo/runtime_observability.v1.schema.json",
    "contracts/openapi/nex-mo.openapi.yaml",
    *(f"scripts/smoke/{name}" for name in QUALITY_SCRIPTS),
    "tests/test_s117_mo_gpu_model_runtime_observability_closure.py",
    *(f"docs/slices/{name}" for name in SLICE_DOCUMENTS),
)
TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    (
        "requirement_traceability",
        "docs/30_service_specific_requirement_partition.md",
        "MO-FR-005",
    ),
    (
        "authenticated_operations",
        "services/nex-mo/README.md",
        "GET /api/v1/model-runtime-observability",
    ),
    (
        "canonical_schema",
        "contracts/openapi/nex-mo.openapi.yaml",
        "schemas/service/nex_mo/runtime_observability.v1.schema.json",
    ),
    (
        "live_models",
        LIVE_DOCUMENT,
        "Expected runtime models | `3/3`",
    ),
    (
        "live_precision",
        LIVE_DOCUMENT,
        "BF16 precision match | `3/3`",
    ),
    (
        "live_gpu_metrics",
        LIVE_DOCUMENT,
        "GPU association and complete metrics | `3/3`",
    ),
    (
        "live_privacy",
        LIVE_DOCUMENT,
        "Private-value redaction | `PASS`",
    ),
    (
        "closure_index",
        "docs/README.md",
        "1171_s117_mo_gpu_model_runtime_observability_closure.md",
    ),
)


def run_s117_mo_gpu_model_runtime_observability_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "domain": _safe_evidence(run_domain),
        "plan": _safe_evidence(run_plan),
        "collector": _safe_evidence(run_collector),
        "service": _safe_evidence(run_service),
        "api": _safe_evidence(run_api),
        "policy": _safe_evidence(run_policy),
        "contract": _safe_evidence(lambda: run_contract(root)),
    }
    token_status = {item["name"]: item["present"] for item in token_checks}
    evidence["protected_live"] = {
        "status": "PASS"
        if all(
            token_status.get(name, False)
            for name in ("live_models", "live_precision", "live_gpu_metrics", "live_privacy")
        )
        else "FAIL"
    }
    components = {
        "boundary_and_domain": all(
            evidence[name].get("status") == "PASS"
            for name in ("boundary", "domain")
        ),
        "protected_plan_and_collector": all(
            evidence[name].get("status") == "PASS"
            for name in ("plan", "collector")
        ),
        "ttl_service_and_policy": all(
            evidence[name].get("status") == "PASS"
            for name in ("service", "policy")
        ),
        "authenticated_api_and_contract": all(
            evidence[name].get("status") == "PASS"
            for name in ("api", "contract")
        ),
        "protected_live_and_quality": evidence["protected_live"]["status"]
        == "PASS"
        and all(token_status.values()),
    }
    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "all_components_closed": all(components.values()),
        "three_capability_domain_closed": summaries["domain"].get("model_count")
        == 3
        and summaries["domain"].get("precision_match_count") == 3
        and summaries["domain"].get("exposed_private_field_count") == 0,
        "fixed_collector_plan_closed": summaries["plan"].get("target_count") == 3
        and summaries["plan"].get("dtype_count") == 3
        and summaries["collector"].get("private_field_count") == 0,
        "ttl_service_closed": summaries["service"].get("model_count") == 3
        and summaries["service"].get("healthy_count") == 3
        and summaries["service"].get("ttl_seconds") == 30,
        "authenticated_api_closed": summaries["api"].get("authorized_status")
        == 200
        and summaries["api"].get("unauthorized_status") == 401
        and summaries["api"].get("model_count") == 3,
        "threshold_policy_closed": summaries["policy"].get(
            "memory_warn_percent"
        )
        == 90.0
        and summaries["policy"].get("temperature_warn_c") == 85.0,
        "contract_privacy_closed": summaries["contract"].get("check_count") == 9
        and summaries["contract"].get("passed_check_count") == 9
        and summaries["contract"].get("forbidden_field_count") == 7,
        "protected_dgx_live_closed": evidence["protected_live"]["status"]
        == "PASS",
        "mo_fr_005_superseded_as_implemented": decision["traceability"]
        == {
            "requirement_id": "MO-FR-005",
            "s111_baseline_status": "PARTIAL",
            "s117_current_status": "IMPLEMENTED",
        },
        "ephemeral_persistence_scope_closed": decision["persistence"]
        == "process_local_ttl_no_table"
        and decision["new_table_added"] is False
        and decision["postgres_smoke_required"] is False,
        "tiered_quality_cadence_preserved": decision["quality_cadence"]
        == {
            "slice_gate": "1162-1170",
            "checkpoint_gate": "1166",
            "full_gate": "1171",
        },
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1171",
        "slice_range": SLICE_RANGE,
        "requirement": "S117",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None
            if passed
            else "s117_mo_gpu_model_runtime_observability_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S118" if passed else "BLOCKED",
        "feature_readiness": (
            "MO_GPU_MODEL_RUNTIME_OBSERVABLE" if passed else "INCOMPLETE"
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
            "model_count": summaries["domain"].get("model_count", 0),
            "contract_check_count": summaries["contract"].get("check_count", 0),
            "live_model_count": 3 if evidence["protected_live"]["status"] == "PASS" else 0,
            "missing_file_count": sum(not item["present"] for item in required_files),
            "missing_token_count": sum(not item["present"] for item in token_checks),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "components": components,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S118" if passed else "blocked",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "feature_scope": "mo_gpu_and_model_runtime_observability",
        "traceability": {
            "requirement_id": "MO-FR-005",
            "s111_baseline_status": "PARTIAL",
            "s117_current_status": "IMPLEMENTED",
        },
        "required_capabilities": ("embedding", "reranking", "generation"),
        "collection_modes": ("mock", "protected_ssh"),
        "default_ttl_seconds": 30,
        "thresholds": {
            "gpu_memory_warn_percent": 90.0,
            "gpu_temperature_warn_c": 85.0,
        },
        "authenticated_path": "/api/v1/model-runtime-observability",
        "persistence": "process_local_ttl_no_table",
        "new_table_added": False,
        "postgres_smoke_required": False,
        "protected_dgx_live_required": True,
        "readiness_coupling": "diagnostic_only",
        "quality_cadence": {
            "slice_gate": "1162-1170",
            "checkpoint_gate": "1166",
            "full_gate": "1171",
        },
        "next_requirement_scope": "S118_mo_catalog_and_alias_lifecycle",
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
        "s117_mo_gpu_model_runtime_observability_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"components={summary.get('closed_component_count', 0)}/"
        f"{summary.get('component_count', 0)} "
        f"models={summary.get('model_count', 0)} "
        f"live={summary.get('live_model_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s117_mo_gpu_model_runtime_observability_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
