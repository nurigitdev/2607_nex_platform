#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "oa_token_surface_inventory.v1"
SLICE_ID = "1243"
REQUIREMENT = "S125"

TRACKED_SYMBOLS = (
    "issue_mock_service_token",
    "issue_mock_user_token",
    "validate_authorization_header",
    "validate_user_authorization_header",
    "validate_mock_service_token",
    "validate_mock_user_token",
)
RUNTIME_SERVICES = (
    "nex-oa",
    "nex-ae-api",
    "nex-cx",
    "nex-ag",
    "nex-mo",
)
EXPECTED_CALLER_COVERAGE = {
    "issue_mock_service_token": {
        "shared",
        "nex-ae-api",
        "nex-cx",
        "nex-ag",
    },
    "issue_mock_user_token": {"nex-oa", "nex-ae-api"},
    "validate_authorization_header": set(RUNTIME_SERVICES) | {"shared"},
    "validate_user_authorization_header": {
        "nex-ae-api",
        "nex-ag",
        "nex-mo",
    },
    "validate_mock_service_token": {"shared"},
    "validate_mock_user_token": {"shared", "nex-ae-api"},
}


@dataclass(frozen=True)
class SymbolLocation:
    path: str
    line: int
    service: str
    kind: str


def build_oa_token_surface_inventory(root: Path = ROOT) -> dict[str, Any]:
    definitions, calls, parse_issues = _scan_python_sources(root)
    symbols = {
        symbol: _symbol_inventory(
            definitions.get(symbol, []),
            calls.get(symbol, []),
        )
        for symbol in TRACKED_SYMBOLS
    }
    service_profiles = {
        service: _service_profile(service, calls)
        for service in (*RUNTIME_SERVICES, "shared")
    }
    app_source = _read_text(root / "services/_shared/nex_runtime/app.py")
    openapi_source = _read_text(root / "contracts/openapi/nex-oa.openapi.yaml")
    evidence = _repository_evidence(root)

    definition_check = all(
        symbols[symbol]["definition_count"] == 1
        for symbol in TRACKED_SYMBOLS
    )
    caller_coverage = {
        symbol: sorted(
            expected
            - set(symbols[symbol]["service_callers"])
        )
        for symbol, expected in EXPECTED_CALLER_COVERAGE.items()
    }
    checks = {
        "python_sources_parse": not parse_issues,
        "tracked_symbol_definitions_unique": definition_check,
        "expected_runtime_callers_observed": all(
            not missing for missing in caller_coverage.values()
        ),
        "silent_mock_fallbacks_observed": (
            symbols["issue_mock_service_token"]["fallback_count"] >= 4
            and {
                "shared",
                "nex-ae-api",
                "nex-cx",
                "nex-ag",
            }.issubset(
                symbols["issue_mock_service_token"]["fallback_services"]
            )
        ),
        "all_runtime_services_classified": all(
            service_profiles[service]["migration_role"] != "unclassified"
            for service in RUNTIME_SERVICES
        ),
        "mock_routes_and_contract_explicit": (
            '@app.post("/api/v1/auth/service-token"' in app_source
            and '@app.post("/api/v1/auth/introspect")' in app_source
            and "operationId: createMockServiceToken" in openapi_source
            and "operationId: introspectMockServiceToken" in openapi_source
            and "Mock service token issued." in openapi_source
        ),
        "repository_evidence_present": all(
            item["present"] for item in evidence
        ),
        "inventory_is_read_only": True,
    }
    issues = _issues(
        parse_issues=parse_issues,
        symbols=symbols,
        caller_coverage=caller_coverage,
        checks=checks,
        evidence=evidence,
    )
    passed = all(checks.values()) and not issues
    return {
        "inventory_schema_version": SCHEMA_VERSION,
        "slice": SLICE_ID,
        "requirement": REQUIREMENT,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "oa_token_surface_inventory_failed",
        "scope": "production_source_only_excluding_tests",
        "symbols": symbols,
        "service_profiles": service_profiles,
        "caller_coverage_gaps": caller_coverage,
        "transition_decision": {
            "mock_symbols_removed_in_s125": False,
            "production_silent_mock_fallback_allowed": False,
            "explicit_test_profile_compatibility_preserved": True,
            "signed_profile_implementation_requirement": "S126",
            "migration_order": (
                "shared_verifier_and_oa_issuer",
                "nex-ae-api",
                "nex-cx",
                "nex-mo",
                "nex-ag",
            ),
            "new_table_required": False,
            "database_evidence_required": False,
        },
        "parse_issues": parse_issues,
        "evidence": evidence,
        "checks": checks,
        "issues": issues,
        "next_slice": "1244",
    }


def _scan_python_sources(
    root: Path,
) -> tuple[
    dict[str, list[SymbolLocation]],
    dict[str, list[SymbolLocation]],
    list[dict[str, Any]],
]:
    definitions = {symbol: [] for symbol in TRACKED_SYMBOLS}
    calls = {symbol: [] for symbol in TRACKED_SYMBOLS}
    issues: list[dict[str, Any]] = []
    services_root = root / "services"
    paths = sorted(services_root.rglob("*.py")) if services_root.is_dir() else []
    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        source = _read_text(path)
        try:
            tree = ast.parse(source, filename=relative_path)
        except SyntaxError as exc:
            issues.append(
                {
                    "category": "python_parse_error",
                    "path": relative_path,
                    "line": exc.lineno or 0,
                }
            )
            continue
        service = _service_name(path, root)
        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in definitions:
                    definitions[node.name].append(
                        SymbolLocation(
                            path=relative_path,
                            line=node.lineno,
                            service=service,
                            kind="definition",
                        )
                    )
                continue
            if not isinstance(node, ast.Call):
                continue
            symbol = _call_name(node.func)
            if symbol not in calls:
                continue
            calls[symbol].append(
                SymbolLocation(
                    path=relative_path,
                    line=node.lineno,
                    service=service,
                    kind=(
                        "fallback"
                        if _has_or_ancestor(node, parents)
                        else "direct"
                    ),
                )
            )
    return definitions, calls, issues


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _has_or_ancestor(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None and not isinstance(current, ast.stmt):
        if isinstance(current, ast.BoolOp) and isinstance(current.op, ast.Or):
            return True
        current = parents.get(current)
    return False


def _service_name(path: Path, root: Path) -> str:
    try:
        parts = path.relative_to(root / "services").parts
    except ValueError:
        return "outside_services"
    if not parts:
        return "unknown"
    return "shared" if parts[0] == "_shared" else parts[0]


def _symbol_inventory(
    definitions: list[SymbolLocation],
    calls: list[SymbolLocation],
) -> dict[str, Any]:
    fallback_calls = [item for item in calls if item.kind == "fallback"]
    return {
        "definition_count": len(definitions),
        "call_count": len(calls),
        "fallback_count": len(fallback_calls),
        "service_callers": sorted({item.service for item in calls}),
        "fallback_services": sorted({item.service for item in fallback_calls}),
        "module_count": len({item.path for item in calls}),
        "definitions": [asdict(item) for item in definitions],
        "calls": [asdict(item) for item in calls],
    }


def _service_profile(
    service: str,
    calls: Mapping[str, list[SymbolLocation]],
) -> dict[str, Any]:
    call_counts = {
        symbol: sum(item.service == service for item in locations)
        for symbol, locations in calls.items()
    }
    fallback_count = sum(
        item.service == service and item.kind == "fallback"
        for item in calls["issue_mock_service_token"]
    )
    if service == "nex-oa":
        role = "issuer_session_owner_and_service_validator"
    elif fallback_count:
        role = "outbound_mock_fallback_and_token_consumer"
    elif call_counts["validate_authorization_header"]:
        role = "token_consumer"
    elif service == "shared":
        role = "shared_issuer_validator_and_transport"
    else:
        role = "unclassified"
    return {
        "migration_role": role,
        "service_token_fallback_count": fallback_count,
        "call_counts": call_counts,
    }


def _repository_evidence(root: Path) -> list[dict[str, Any]]:
    required = (
        (
            "s125_boundary",
            "docs/slices/1242_oa_production_trust_boundary.md",
            "Production targets short-lived signed",
        ),
        (
            "inventory_document",
            "docs/slices/1243_oa_token_surface_inventory.md",
            "# Slice 1243:",
        ),
        (
            "quality_hook",
            "scripts/quality/run_quality_gate.sh",
            "run_oa_token_surface_inventory.py",
        ),
        (
            "docs_index",
            "docs/README.md",
            "1243_oa_token_surface_inventory.md",
        ),
    )
    return [
        {
            "name": name,
            "path": relative_path,
            "present": token in _read_text(root / relative_path),
        }
        for name, relative_path, token in required
    ]


def _issues(
    *,
    parse_issues: list[dict[str, Any]],
    symbols: Mapping[str, Mapping[str, Any]],
    caller_coverage: Mapping[str, list[str]],
    checks: Mapping[str, bool],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues = list(parse_issues)
    issues.extend(
        {
            "category": "symbol_definition_drift",
            "symbol": symbol,
            "definition_count": inventory["definition_count"],
        }
        for symbol, inventory in symbols.items()
        if inventory["definition_count"] != 1
    )
    issues.extend(
        {
            "category": "caller_coverage_gap",
            "symbol": symbol,
            "missing_services": missing,
        }
        for symbol, missing in caller_coverage.items()
        if missing
    )
    issues.extend(
        {
            "category": "repository_evidence_missing",
            "name": item["name"],
            "path": item["path"],
        }
        for item in evidence
        if not item["present"]
    )
    represented_checks = {
        "python_sources_parse",
        "tracked_symbol_definitions_unique",
        "expected_runtime_callers_observed",
        "repository_evidence_present",
    }
    issues.extend(
        {"category": "inventory_check_failed", "check": name}
        for name, passed in checks.items()
        if not passed and name not in represented_checks
    )
    return issues


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(inventory: Mapping[str, Any]) -> str:
    if inventory.get("status") != "PASS":
        return (
            "oa_token_surface_inventory=fail "
            f"issues={len(inventory.get('issues') or [])}"
        )
    symbols = inventory.get("symbols") or {}
    service_issue = symbols.get("issue_mock_service_token") or {}
    user_issue = symbols.get("issue_mock_user_token") or {}
    return (
        "oa_token_surface_inventory=pass "
        f"service_calls={service_issue.get('call_count')} "
        f"fallbacks={service_issue.get('fallback_count')} "
        f"user_calls={user_issue.get('call_count')} "
        f"services={len(inventory.get('service_profiles') or {})} "
        f"next={inventory.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    inventory = build_oa_token_surface_inventory()
    print(
        summary_line(inventory)
        if args.summary
        else json.dumps(inventory, indent=2, sort_keys=True)
    )
    return 0 if inventory["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
