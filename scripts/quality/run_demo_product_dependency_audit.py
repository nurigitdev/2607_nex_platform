#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path("reports/quality/demo-product-dependency-audit.json")
AUDIT_SCHEMA_VERSION = "demo_product_dependency_audit.v1"

FORBIDDEN_DEMO_DEPENDENCIES = (
    "demo_fixture",
    "demo_processes",
    "p8_demo_runtime_composition",
    "p8_demo_semantic_activation",
)

# These are historical compatibility adapters, not canonical product modules.
EXPLICIT_DEMO_WRAPPERS = frozenset(
    {
        "services/_shared/nex_runtime/demo_compose.py",
        "services/_shared/nex_runtime/demo_oci_release.py",
        "services/nex-ae-api/nex_ae_api/demo_runtime.py",
        "services/nex-ae-api/nex_ae_api/p8_demo_controlled_skill.py",
        "services/nex-ae-api/nex_ae_api/p8_demo_semantic_activation.py",
    }
)


@dataclass(frozen=True)
class CompatibilityEdge:
    edge_id: str
    path: str
    required_imports: tuple[str, ...]


COMPATIBILITY_EDGES = (
    CompatibilityEdge(
        "openbao_canonical_readiness",
        "scripts/deployment/run_canonical_platform_trust_admission.py",
        ("nex_runtime.openbao_provisioning.provision_openbao_environment",),
    ),
    CompatibilityEdge(
        "object_storage_canonical_readiness",
        "scripts/deployment/run_canonical_platform_installed_acceptance.py",
        (
            (
                "nex_runtime.object_storage_provisioning."
                "provision_object_storage_environment"
            ),
        ),
    ),
    CompatibilityEdge(
        "model_provider_canonical_readiness",
        "scripts/smoke/run_dgx_live_provider_preflight.py",
        ("nex_mo.model_provider_admission.admit_model_provider_readiness",),
    ),
    CompatibilityEdge(
        "s10b_generic_runtime_composition",
        "services/nex-ae-api/nex_ae_api/p8_demo_runtime_composition.py",
        ("nex_ae_api.runtime_composition.build_installed_runtime_composition",),
    ),
    CompatibilityEdge(
        "s10b_installed_runtime",
        "scripts/smoke/run_p8_demo_s10b_installed_runtime.py",
        (
            (
                "nex_ae_api.p8_demo_runtime_composition."
                "build_installed_p8_runtime_composition"
            ),
        ),
    ),
    CompatibilityEdge(
        "s10c_result_closure",
        "scripts/smoke/run_p8_demo_s10c_installed_result_closure.py",
        (("run_p8_demo_s10b_installed_runtime.run_p8_demo_s10b_installed_runtime"),),
    ),
    CompatibilityEdge(
        "canonical_golden_a_product_registry",
        "scripts/deployment/run_canonical_platform_golden_journey.py",
        (
            "run_canonical_platform_installed_acceptance",
            "nex_ae_api.product_capabilities.load_product_capability_registry",
        ),
    ),
)


@dataclass(frozen=True)
class AuditFinding:
    code: str
    path: str
    line: int
    detail: str


def audit_repository(root: Path = ROOT) -> dict[str, Any]:
    findings: list[AuditFinding] = []
    parsed: dict[str, ast.Module | None] = {}
    service_root = root / "services"
    product_file_count = 0

    if not service_root.is_dir():
        findings.append(
            AuditFinding(
                "PRODUCT_SOURCE_INVENTORY_MISSING",
                "services",
                0,
                "canonical product source inventory is unavailable",
            )
        )
    else:
        for path in sorted(service_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix()
            tree = _parse_source(path, relative, findings)
            parsed[relative] = tree
            if relative in EXPLICIT_DEMO_WRAPPERS:
                continue
            product_file_count += 1
            if tree is not None:
                findings.extend(_forbidden_import_findings(tree, relative))

    for relative in sorted(EXPLICIT_DEMO_WRAPPERS):
        path = root / relative
        if not path.is_file():
            findings.append(
                AuditFinding(
                    "DEMO_WRAPPER_MISSING",
                    relative,
                    0,
                    "explicit Demo compatibility wrapper is unavailable",
                )
            )

    edge_status: dict[str, str] = {}
    for edge in COMPATIBILITY_EDGES:
        path = root / edge.path
        tree = parsed.get(edge.path)
        if edge.path not in parsed:
            if not path.is_file():
                findings.append(
                    AuditFinding(
                        "COMPATIBILITY_SOURCE_MISSING",
                        edge.path,
                        0,
                        f"compatibility edge source is unavailable: {edge.edge_id}",
                    )
                )
                edge_status[edge.edge_id] = "FAIL"
                continue
            tree = _parse_source(path, edge.path, findings)
            parsed[edge.path] = tree
        if tree is None:
            edge_status[edge.edge_id] = "FAIL"
            continue
        imported = _imported_names(tree)
        missing = sorted(set(edge.required_imports) - imported)
        if missing:
            findings.append(
                AuditFinding(
                    "CANONICAL_COMPATIBILITY_EDGE_MISSING",
                    edge.path,
                    0,
                    f"canonical compatibility edge is missing: {edge.edge_id}",
                )
            )
            edge_status[edge.edge_id] = "FAIL"
        else:
            edge_status[edge.edge_id] = "PASS"

    findings.sort(key=lambda item: (item.path, item.line, item.code))
    canonical_clean = not any(
        item.code == "FORBIDDEN_DEMO_DEPENDENCY" for item in findings
    )
    compatibility_ready = all(
        edge_status.get(edge.edge_id) == "PASS" for edge in COMPATIBILITY_EDGES
    )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "PASS" if not findings else "FAIL",
        "canonical_product_file_count": product_file_count,
        "explicit_demo_wrapper_count": len(EXPLICIT_DEMO_WRAPPERS),
        "forbidden_dependency_names": list(FORBIDDEN_DEMO_DEPENDENCIES),
        "canonical_product_paths_clean": canonical_clean,
        "current_platform_components_authoritative": compatibility_ready,
        "compatibility_edges": edge_status,
        "historical_p8_demo_regressions": {
            "S10": edge_status.get("object_storage_canonical_readiness") == "PASS",
            "S10B": edge_status.get("s10b_installed_runtime") == "PASS"
            and edge_status.get("s10b_generic_runtime_composition") == "PASS",
            "S10C": edge_status.get("s10c_result_closure") == "PASS",
            "S11": edge_status.get("canonical_golden_a_product_registry") == "PASS",
        },
        "findings": [asdict(item) for item in findings],
        "content_included": False,
        "secret_included": False,
    }


def _parse_source(
    path: Path,
    relative: str,
    findings: list[AuditFinding],
) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError) as exc:
        line = exc.lineno if isinstance(exc, SyntaxError) and exc.lineno else 0
        findings.append(
            AuditFinding(
                "SOURCE_PARSE_FAILED",
                relative,
                line,
                "source cannot be parsed for dependency ownership",
            )
        )
        return None


def _forbidden_import_findings(tree: ast.AST, relative: str) -> list[AuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for imported in _node_imported_names(node):
            dependency = next(
                (
                    name
                    for name in FORBIDDEN_DEMO_DEPENDENCIES
                    if name in imported.split(".")
                ),
                None,
            )
            if dependency is not None:
                findings.append(
                    AuditFinding(
                        "FORBIDDEN_DEMO_DEPENDENCY",
                        relative,
                        node.lineno,
                        f"canonical product source imports Demo dependency: {dependency}",
                    )
                )
    return findings


def _imported_names(tree: ast.AST) -> set[str]:
    return {
        imported
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for imported in _node_imported_names(node)
    }


def _node_imported_names(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    module = node.module or ""
    return tuple(
        f"{module}.{alias.name}" if module else alias.name for alias in node.names
    )


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "demo_product_dependency_audit="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"product_files={evidence.get('canonical_product_file_count', 0)} "
        f"wrappers={evidence.get('explicit_demo_wrapper_count', 0)} "
        f"edges={sum(value == 'PASS' for value in dict(evidence.get('compatibility_edges') or {}).values())}/"
        f"{len(COMPATIBILITY_EDGES)} "
        f"findings={len(evidence.get('findings') or [])}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = audit_repository(args.root)
    report = args.report if args.report.is_absolute() else args.root / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover - exercised by quality gates
    raise SystemExit(main())
