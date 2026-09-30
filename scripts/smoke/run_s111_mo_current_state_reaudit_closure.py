#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT / "scripts" / "smoke"))

from nex_mo.catalog_config_audit import (  # noqa: E402
    build_mo_catalog_config_drift_audit as run_catalog,
)
from nex_mo.contract_api_drift_audit import (  # noqa: E402
    build_mo_contract_api_drift_audit as run_contract,
)
from nex_mo.current_state_traceability import (  # noqa: E402
    build_mo_capability_traceability_inventory as run_traceability,
)
from nex_mo.precision_resource_audit import (  # noqa: E402
    build_mo_precision_resource_safety_audit as run_precision,
)
from nex_mo.profile_privacy_audit import (  # noqa: E402
    build_mo_profile_privacy_refactor_checkpoint as run_privacy,
)
from nex_mo.resilience_readiness_audit import (  # noqa: E402
    build_mo_resilience_telemetry_readiness_audit as run_resilience,
)
from nex_mo.runtime_coupling_audit import (  # noqa: E402
    build_mo_runtime_coupling_audit as run_coupling,
)
from run_mo_current_state_reaudit_boundary import (  # noqa: E402
    run_mo_current_state_reaudit_boundary as run_boundary,
)


SCHEMA_VERSION = "s111_mo_current_state_reaudit_closure.v1"
SLICE_RANGE = "1102-1111"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
LIVE_EVIDENCE_DOC = "docs/slices/1110_mo_protected_dgx_live_reaudit.md"

REQUIRED_FILES = (
    "services/nex-mo/nex_mo/providers.py",
    "services/nex-mo/nex_mo/remote_provider.py",
    "services/nex-mo/nex_mo/current_state_traceability.py",
    "services/nex-mo/nex_mo/catalog_config_audit.py",
    "services/nex-mo/nex_mo/runtime_coupling_audit.py",
    "services/nex-mo/nex_mo/profile_privacy_audit.py",
    "services/nex-mo/nex_mo/precision_resource_audit.py",
    "services/nex-mo/nex_mo/contract_api_drift_audit.py",
    "services/nex-mo/nex_mo/resilience_readiness_audit.py",
    "scripts/smoke/run_mo_dgx_process_dtype_probe.py",
    "scripts/smoke/run_protected_remote_provider_live_smoke.py",
    "scripts/smoke/run_s111_mo_current_state_reaudit_closure.py",
    "tests/test_s111_mo_current_state_reaudit_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("1102", "mo_current_state_reaudit_boundary"),
            ("1103", "mo_capability_traceability_inventory"),
            ("1104", "mo_provider_catalog_configuration_drift_audit"),
            ("1105", "mo_remote_transport_runtime_coupling_audit"),
            ("1106", "mo_route_privacy_refactoring_checkpoint"),
            ("1107", "mo_model_precision_resource_safety_audit"),
            ("1108", "mo_contract_api_drift_audit"),
            ("1109", "mo_resilience_telemetry_readiness_audit"),
            ("1110", "mo_protected_dgx_live_reaudit"),
            ("1111", "s111_mo_current_state_reaudit_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "quality_dtype_probe",
        QUALITY_GATE_PATH,
        "run_mo_dgx_process_dtype_probe.py",
    ),
    (
        "quality_live_smoke",
        QUALITY_GATE_PATH,
        "run_protected_remote_provider_live_smoke.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s111_mo_current_state_reaudit_closure.py",
    ),
    ("live_preflight", LIVE_EVIDENCE_DOC, "Provider preflight | 3/3 PASS"),
    (
        "live_requests",
        LIVE_EVIDENCE_DOC,
        "Protected provider requests | 3/3 PASS",
    ),
    (
        "live_model_identity",
        LIVE_EVIDENCE_DOC,
        "Expected model identity | 3/3 PASS",
    ),
    (
        "live_bf16",
        LIVE_EVIDENCE_DOC,
        "Explicit BF16 process dtype | 3/3 PASS",
    ),
    ("live_redaction", LIVE_EVIDENCE_DOC, "Evidence redaction | PASS"),
    (
        "docs_live_index",
        "docs/README.md",
        "1110_mo_protected_dgx_live_reaudit.md",
    ),
    (
        "docs_closure_index",
        "docs/README.md",
        "1111_s111_mo_current_state_reaudit_closure.md",
    ),
)


def run_s111_mo_current_state_reaudit_closure(
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
    audits = {
        "boundary": _safe_evidence(lambda: run_boundary(root)),
        "traceability": _safe_evidence(lambda: run_traceability(root)),
        "catalog": _safe_evidence(lambda: run_catalog(root)),
        "runtime_coupling": _safe_evidence(lambda: run_coupling(root)),
        "privacy": _safe_evidence(lambda: run_privacy(root)),
        "precision": _safe_evidence(lambda: run_precision(root)),
        "contract": _safe_evidence(lambda: run_contract(root)),
        "resilience": _safe_evidence(lambda: run_resilience(root)),
    }
    summaries = {
        name: _mapping(evidence.get("summary"))
        for name, evidence in audits.items()
    }
    live_evidence = {
        item["name"]: item["present"]
        for item in token_checks
        if item["name"].startswith("live_")
    }
    boundary_decision = _mapping(audits["boundary"].get("decision"))
    handoff = _s112_handoff()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_audits_passed": all(
            evidence.get("status") == "PASS" for evidence in audits.values()
        ),
        "all_mo_requirements_traceable": (
            summaries["traceability"].get("requirement_count") == 5
            and summaries["traceability"].get("traceable_count") == 5
            and summaries["traceability"].get("partial_count") == 2
        ),
        "privacy_boundary_repaired": (
            audits["privacy"].get("refactor_readiness")
            == "PRIVACY_BOUNDARY_REPAIRED"
            and summaries["privacy"].get("forbidden_public_field_count") == 0
        ),
        "live_provider_and_dtype_evidence_passed": (
            len(live_evidence) == 5 and all(live_evidence.values())
        ),
        "remaining_catalog_drift_quantified": (
            summaries["catalog"].get("drift_count") == 4
            and summaries["catalog"].get("high_risk_count") == 0
        ),
        "ordered_refactoring_quantified": (
            summaries["runtime_coupling"].get("refactor_required_count") == 5
            and audits["runtime_coupling"].get("refactoring_readiness")
            == "ORDERED_REFACTOR_REQUIRED_BEFORE_NEW_MO_FEATURES"
        ),
        "contract_drift_quantified": (
            0 <= int(summaries["contract"].get("drift_count") or 0) <= 28
            and audits["contract"].get("contract_readiness")
            in {"GAPS_CONFIRMED", "HARDENED"}
        ),
        "runtime_gaps_quantified": (
            0 < int(summaries["resilience"].get("runtime_gap_count") or 0) <= 5
            and audits["resilience"].get("operations_readiness") == "GAPS_CONFIRMED"
        ),
        "database_boundary_preserved": (
            boundary_decision.get("actual_test_database_evidence_required") is False
            and boundary_decision.get("new_table_required") is False
        ),
        "s112_handoff_ordered": (
            handoff["target_requirement"] == "S112"
            and [item["priority"] for item in handoff["work_items"]]
            == ["P0", "P0", "P0", "P0", "P1", "P1", "P1", "P2"]
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "1111",
        "slice_range": SLICE_RANGE,
        "requirement": "S111",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s111_mo_reaudit_closure_failed"
        ),
        "closure_readiness": (
            "READY_FOR_TARGETED_S112_HARDENING" if status == "PASS" else "BLOCKED"
        ),
        "feature_readiness": "CONFIRMED_GAPS_NOT_FEATURE_COMPLETE",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "audit_count": len(audits),
            "passed_audit_count": sum(
                evidence.get("status") == "PASS" for evidence in audits.values()
            ),
            "traceable_requirement_count": summaries["traceability"].get(
                "traceable_count", 0
            ),
            "catalog_drift_count": summaries["catalog"].get("drift_count", 0),
            "required_refactoring_count": summaries["runtime_coupling"].get(
                "refactor_required_count", 0
            ),
            "contract_drift_count": summaries["contract"].get("drift_count", 0),
            "runtime_gap_count": summaries["resilience"].get(
                "runtime_gap_count", 0
            ),
            "live_evidence_count": sum(live_evidence.values()),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "audit_statuses": {
            name: evidence.get("status") for name, evidence in audits.items()
        },
        "live_evidence": live_evidence,
        "handoff": handoff,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S112",
    }


def _s112_handoff() -> dict[str, Any]:
    return {
        "target_requirement": "S112",
        "title": "MO provider runtime and operations hardening",
        "work_items": [
            {
                "priority": "P0",
                "work_item": "split remote transport normalization and telemetry modules",
            },
            {
                "priority": "P0",
                "work_item": "separate provider registry from public profile projection",
            },
            {
                "priority": "P0",
                "work_item": "compose provider-aware readiness from protected probes",
            },
            {
                "priority": "P0",
                "work_item": "close OpenAPI schema security and fixture drift",
            },
            {
                "priority": "P1",
                "work_item": "add bounded retry execution with failure taxonomy",
            },
            {
                "priority": "P1",
                "work_item": "add restart-safe aggregate provider telemetry",
            },
            {
                "priority": "P1",
                "work_item": "project protected GPU memory and utilization metrics",
            },
            {
                "priority": "P2",
                "work_item": "migrate stable aliases and retire legacy PCX profile use",
            },
        ],
        "guardrails": [
            "refactor oversized modules before adding provider-control features",
            "preserve capability aliases and current route behavior slice by slice",
            "keep endpoints credentials model paths and process arguments private",
            "keep mock regression deterministic and live evidence explicitly protected",
            "require a deliberate persistence decision before adding an MO database",
            "retain explicit bfloat16 launch policy for all current DGX providers",
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
        "s111_mo_current_state_reaudit_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"audits={summary.get('passed_audit_count', 0)}/"
        f"{summary.get('audit_count', 0)} "
        f"live={summary.get('live_evidence_count', 0)}/5 "
        f"refactors={summary.get('required_refactoring_count', 0)} "
        f"contract_drift={summary.get('contract_drift_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s111_mo_current_state_reaudit_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
