from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ModuleRule:
    module_id: str
    path: str
    max_lines: int
    forbidden_tokens: tuple[str, ...] = ()


MODULE_RULES = (
    ModuleRule("provider_api_composition", "services/nex-mo/nex_mo/providers.py", 550),
    ModuleRule(
        "remote_execution_composition",
        "services/nex-mo/nex_mo/remote_provider.py",
        1_200,
        ("from nex_mo.providers import",),
    ),
    ModuleRule(
        "provider_catalog",
        "services/nex-mo/nex_mo/provider_catalog.py",
        300,
        ("import httpx", "sqlalchemy"),
    ),
    ModuleRule(
        "provider_projection",
        "services/nex-mo/nex_mo/provider_projection.py",
        180,
        ("import httpx", "sqlalchemy"),
    ),
    ModuleRule(
        "provider_registry",
        "services/nex-mo/nex_mo/provider_registry.py",
        150,
        ("import httpx", "sqlalchemy"),
    ),
    ModuleRule(
        "provider_normalization",
        "services/nex-mo/nex_mo/provider_normalization.py",
        400,
        ("import httpx", "sqlalchemy"),
    ),
    ModuleRule(
        "provider_transport",
        "services/nex-mo/nex_mo/provider_transport.py",
        220,
        ("sqlalchemy",),
    ),
    ModuleRule(
        "provider_telemetry",
        "services/nex-mo/nex_mo/provider_telemetry.py",
        350,
        ("import httpx", "sqlalchemy"),
    ),
)


def build_mo_runtime_hardening_audit(
    root: Path = ROOT,
    *,
    rules: Sequence[ModuleRule] = MODULE_RULES,
) -> dict[str, Any]:
    modules = [_inspect_module(root, rule) for rule in rules]
    providers_source = _read(root / "services/nex-mo/nex_mo/providers.py")
    remote_source = _read(root / "services/nex-mo/nex_mo/remote_provider.py")
    required_remote_dependencies = {
        "provider_catalog": "from nex_mo.provider_catalog import (",
        "provider_normalization": "from nex_mo.provider_normalization import (",
        "provider_registry": "from nex_mo.provider_registry import (",
        "provider_telemetry": "from nex_mo.provider_telemetry import (",
        "provider_transport": "from nex_mo.provider_transport import (",
    }
    compatibility_exports = {
        "catalog": "from nex_mo.provider_catalog import (" in providers_source,
        "registry": "from nex_mo.provider_registry import (" in providers_source,
        "normalization": required_remote_dependencies["provider_normalization"]
        in remote_source,
        "telemetry": required_remote_dependencies["provider_telemetry"]
        in remote_source,
        "transport": required_remote_dependencies["provider_transport"]
        in remote_source,
    }
    issues = [
        {
            "category": "runtime_module_rule_failed",
            "module_id": item["module_id"],
            "path": item["path"],
        }
        for item in modules
        if not item["rule_passed"]
    ]
    checks = {
        "module_inventory_complete": len(modules) == 8,
        "module_rules_pass": not issues,
        "remote_dependencies_explicit": all(
            token in remote_source for token in required_remote_dependencies.values()
        ),
        "remote_api_back_dependency_removed": "from nex_mo.providers import"
        not in remote_source,
        "compatibility_exports_preserved": all(compatibility_exports.values()),
        "telemetry_store_boundary_explicit": "class ProviderTelemetryStore"
        in _read(root / "services/nex-mo/nex_mo/provider_telemetry.py"),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_runtime_hardening_audit.v1",
        "slice": "1119",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_runtime_hardening_audit_failed",
        "readiness": "DECOMPOSITION_HARDENED" if passed else "BLOCKED",
        "checks": checks,
        "summary": {
            "module_count": len(modules),
            "module_rule_pass_count": sum(item["rule_passed"] for item in modules),
            "completed_boundary_count": 5,
            "compatibility_export_count": sum(compatibility_exports.values()),
            "issue_count": len(issues),
        },
        "modules": modules,
        "compatibility_exports": compatibility_exports,
        "persistence_status": "HYBRID_DECIDED_NOT_IMPLEMENTED",
        "issues": issues,
        "next_slice": "1120",
    }


def _inspect_module(root: Path, rule: ModuleRule) -> dict[str, Any]:
    path = root / rule.path
    source = _read(path)
    line_count = len(source.splitlines())
    forbidden_found = [token for token in rule.forbidden_tokens if token in source]
    present = path.is_file()
    return {
        "module_id": rule.module_id,
        "path": rule.path,
        "present": present,
        "line_count": line_count,
        "max_lines": rule.max_lines,
        "within_budget": present and line_count <= rule.max_lines,
        "forbidden_tokens_found": forbidden_found,
        "rule_passed": present
        and line_count <= rule.max_lines
        and not forbidden_found,
    }


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
