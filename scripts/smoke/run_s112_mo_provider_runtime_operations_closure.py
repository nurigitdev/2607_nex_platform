#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.runtime_hardening_audit import (  # noqa: E402
    build_mo_runtime_hardening_audit as run_architecture,
)
from nex_mo.runtime_hardening_boundary import (  # noqa: E402
    build_mo_runtime_hardening_boundary as run_boundary,
)
from run_mo_provider_catalog_extraction import (  # noqa: E402
    run_mo_provider_catalog_extraction as run_catalog,
)
from run_mo_provider_normalization_extraction import (  # noqa: E402
    run_mo_provider_normalization_extraction as run_normalization,
)
from run_mo_provider_operations_compatibility import (  # noqa: E402
    run_mo_provider_operations_compatibility as run_operations,
)
from run_mo_provider_projection_extraction import (  # noqa: E402
    run_mo_provider_projection_extraction as run_projection,
)
from run_mo_provider_registry_decoupling import (  # noqa: E402
    run_mo_provider_registry_decoupling as run_registry,
)
from run_mo_provider_telemetry_extraction import (  # noqa: E402
    run_mo_provider_telemetry_extraction as run_telemetry,
)
from run_mo_provider_transport_extraction import (  # noqa: E402
    run_mo_provider_transport_extraction as run_transport,
)


SCHEMA_VERSION = "s112_mo_provider_runtime_operations_closure.v1"
SLICE_RANGE = "1112-1121"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
LIVE_EVIDENCE_DOC = (
    "docs/slices/1120_mo_provider_operations_compatibility_evidence.md"
)

REQUIRED_FILES = (
    "services/nex-mo/nex_mo/provider_catalog.py",
    "services/nex-mo/nex_mo/provider_projection.py",
    "services/nex-mo/nex_mo/provider_registry.py",
    "services/nex-mo/nex_mo/provider_normalization.py",
    "services/nex-mo/nex_mo/provider_transport.py",
    "services/nex-mo/nex_mo/provider_telemetry.py",
    "services/nex-mo/nex_mo/runtime_hardening_boundary.py",
    "services/nex-mo/nex_mo/runtime_hardening_audit.py",
    "scripts/smoke/run_mo_provider_operations_compatibility.py",
    "scripts/smoke/run_s112_mo_provider_runtime_operations_closure.py",
    "tests/test_mo_provider_operations_compatibility.py",
    "tests/test_s112_mo_provider_runtime_operations_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1112", "mo_runtime_hardening_boundary"),
            ("1113", "mo_provider_public_projection_extraction"),
            ("1114", "mo_provider_catalog_configuration_extraction"),
            ("1115", "mo_provider_response_normalization_extraction"),
            ("1116", "mo_provider_http_transport_extraction"),
            ("1117", "mo_provider_telemetry_adapter_extraction"),
            ("1118", "mo_provider_registry_composition_decoupling"),
            ("1119", "mo_runtime_decomposition_architecture_guard"),
            ("1120", "mo_provider_operations_compatibility_evidence"),
            ("1121", "s112_mo_provider_runtime_operations_closure"),
        )
    ),
)

QUALITY_SCRIPTS = (
    "run_mo_runtime_hardening_boundary.py",
    "run_mo_provider_projection_extraction.py",
    "run_mo_provider_catalog_extraction.py",
    "run_mo_provider_normalization_extraction.py",
    "run_mo_provider_transport_extraction.py",
    "run_mo_provider_telemetry_extraction.py",
    "run_mo_provider_registry_decoupling.py",
    "run_mo_runtime_hardening_audit.py",
    "run_mo_provider_operations_compatibility.py",
    "run_s112_mo_provider_runtime_operations_closure.py",
)

TOKEN_CHECKS = (
    *(
        (f"quality_{index}", QUALITY_GATE_PATH, script)
        for index, script in enumerate(QUALITY_SCRIPTS, start=1)
    ),
    ("live_profile", LIVE_EVIDENCE_DOC, "provider preflight: PASS"),
    ("live_requests", LIVE_EVIDENCE_DOC, "generation requests: 3/3 PASS"),
    ("live_bf16", LIVE_EVIDENCE_DOC, "confirmed BF16: 3/3 PASS"),
    ("live_explicit", LIVE_EVIDENCE_DOC, "configuration: 3/3 PASS"),
    ("live_redaction", LIVE_EVIDENCE_DOC, "Evidence redaction: PASS"),
    (
        "docs_closure_index",
        "docs/README.md",
        "1121_s112_mo_provider_runtime_operations_closure.md",
    ),
)


def run_s112_mo_provider_runtime_operations_closure(
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
    evidence = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "projection": _safe_evidence(run_projection),
        "catalog": _safe_evidence(lambda: run_catalog(root)),
        "normalization": _safe_evidence(lambda: run_normalization(root)),
        "transport": _safe_evidence(lambda: run_transport(root)),
        "telemetry": _safe_evidence(lambda: run_telemetry(root)),
        "registry": _safe_evidence(lambda: run_registry(root)),
        "architecture": _safe_evidence(lambda: run_architecture(root)),
        "operations": _safe_evidence(run_operations),
    }
    boundary_summary = _mapping(evidence["boundary"].get("summary"))
    architecture_summary = _mapping(evidence["architecture"].get("summary"))
    persistence = _mapping(evidence["boundary"].get("persistence_decision"))
    live_tokens = {
        item["name"]: item["present"]
        for item in token_checks
        if item["name"].startswith("live_")
    }
    handoff = _s113_handoff()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_slice_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "five_runtime_boundaries_complete": (
            boundary_summary.get("refactoring_boundary_count") == 5
            and architecture_summary.get("completed_boundary_count") == 5
        ),
        "eight_runtime_modules_hardened": (
            architecture_summary.get("module_count") == 8
            and architecture_summary.get("module_rule_pass_count") == 8
        ),
        "compatibility_exports_preserved": (
            architecture_summary.get("compatibility_export_count") == 5
        ),
        "protected_live_evidence_complete": (
            len(live_tokens) == 5 and all(live_tokens.values())
        ),
        "hybrid_persistence_decision_preserved": (
            persistence.get("decision") == "HYBRID_PERSISTENCE_BOUNDARY"
            and persistence.get("table_creation_slice") is None
            and evidence["architecture"].get("persistence_status")
            == "HYBRID_DECIDED_NOT_IMPLEMENTED"
        ),
        "s113_handoff_ordered": (
            handoff["target_requirement"] == "S113"
            and [item["requirement"] for item in handoff["ordered_work"]]
            == ["S113", "S114", "S115", "S116", "S117", "S118"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1121",
        "slice_range": SLICE_RANGE,
        "requirement": "S112",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s112_mo_runtime_operations_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_PROVIDER_AWARE_READINESS" if status == "PASS" else "BLOCKED"
        ),
        "feature_readiness": "RUNTIME_HARDENING_COMPLETE_OPERATIONS_FEATURES_DEFERRED",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "runtime_boundary_count": boundary_summary.get(
                "refactoring_boundary_count", 0
            ),
            "hardened_module_count": architecture_summary.get(
                "module_rule_pass_count", 0
            ),
            "compatibility_export_count": architecture_summary.get(
                "compatibility_export_count", 0
            ),
            "live_evidence_count": sum(live_tokens.values()),
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
        "live_evidence": live_tokens,
        "persistence_decision": {
            "decision": persistence.get("decision"),
            "table_created": False,
            "next_durable_slice": "S116",
        },
        "handoff": handoff,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S113",
    }


def _s113_handoff() -> dict[str, Any]:
    return {
        "target_requirement": "S113",
        "title": "MO provider-aware readiness and dependency health",
        "ordered_work": [
            {"requirement": "S113", "work_item": "provider-aware readiness"},
            {"requirement": "S114", "work_item": "contract and API drift closure"},
            {"requirement": "S115", "work_item": "bounded retry and resilience"},
            {"requirement": "S116", "work_item": "durable aggregate telemetry"},
            {"requirement": "S117", "work_item": "GPU resource observability"},
            {"requirement": "S118", "work_item": "catalog and alias lifecycle"},
        ],
        "guardrails": [
            "preserve extracted module ownership and compatibility imports",
            "keep protected endpoints credentials paths commands and payloads private",
            "retain deterministic mock regression and explicit protected live opt-in",
            "keep high-frequency metrics outside PostgreSQL",
            "introduce durable tables only in their owning requirement",
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
        "s112_mo_provider_runtime_operations_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"boundaries={summary.get('runtime_boundary_count', 0)} "
        f"modules={summary.get('hardened_module_count', 0)} "
        f"live={summary.get('live_evidence_count', 0)}/5 "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s112_mo_provider_runtime_operations_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
