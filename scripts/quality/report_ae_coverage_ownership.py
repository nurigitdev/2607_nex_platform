#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for source_root in (ROOT / "services/_shared", ROOT / "scripts/quality"):
    sys.path.insert(0, str(source_root))

from build_mybee_w70_golden_a_quarantine import active_ae_import_graph
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

MANIFEST_PATH = Path("scripts/quality/ae_coverage_ownership.v1.json")
DEFAULT_REPORT = Path(
    "reports/coverage/mybee-w70-ga-ret-02a1-ae-ownership-inventory.json"
)
ALLOWED_SCOPES = frozenset(
    {"ACTIVE_PRODUCT", "ACTIVE_COMPATIBILITY", "HISTORICAL_QUARANTINE"}
)


class AeCoverageOwnershipError(RuntimeError):
    pass


def build_ownership_inventory(
    root: Path = ROOT,
    *,
    manifest: Mapping[str, Any] | None = None,
    coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    document = dict(manifest or _json_object(root / MANIFEST_PATH))
    _validate_manifest(document)

    source_root_text = _required_text(document, "source_root")
    source_root = root / source_root_text
    if not source_root.is_dir():
        raise AeCoverageOwnershipError("AE source root is unavailable")
    modules = sorted(
        path.relative_to(root).as_posix() for path in source_root.rglob("*.py")
    )
    if not modules:
        raise AeCoverageOwnershipError("AE source inventory is empty")

    overrides = _scope_overrides(document, root=root, modules=set(modules))
    default_scope = _required_text(document, "default_scope")
    if default_scope not in ALLOWED_SCOPES:
        raise AeCoverageOwnershipError("default AE ownership scope is invalid")

    quarantine = _json_object(
        root / _required_text(document, "quarantine_manifest_ref")
    )
    quarantine_sources = _quarantine_sources(
        root, quarantine=quarantine, source_root=source_root_text
    )
    declared_historical = {
        path for path, scope in overrides.items() if scope == "HISTORICAL_QUARANTINE"
    }
    if declared_historical != quarantine_sources:
        raise AeCoverageOwnershipError(
            "historical ownership must match the hash-pinned quarantine exactly"
        )

    active_graph = active_ae_import_graph(root)
    historical_conflicts = sorted(active_graph & declared_historical)
    deployment_conflicts = _deployment_conflicts(
        root,
        inputs=_required_string_list(document, "canonical_deployment_inputs"),
        historical_paths=declared_historical,
    )
    module_set = set(modules)
    coverage_files = {
        path: summary
        for path, summary in _coverage_files(coverage).items()
        if path in module_set
    }
    rows = [
        _module_row(
            path,
            scope=overrides.get(path, default_scope),
            active_graph=active_graph,
            coverage_files=coverage_files,
        )
        for path in modules
    ]
    scopes = {
        scope: _scope_summary(rows, scope)
        for scope in sorted(ALLOWED_SCOPES)
    }
    unclassified = [row["path"] for row in rows if row["scope"] not in ALLOWED_SCOPES]
    checks = {
        "manifest_hash_valid": True,
        "all_modules_classified": not unclassified,
        "historical_scope_matches_quarantine": declared_historical
        == quarantine_sources,
        "historical_hashes_match": True,
        "historical_absent_from_active_graph": not historical_conflicts,
        "historical_absent_from_deployment_inputs": not deployment_conflicts,
    }
    return {
        "schema_version": "ae.coverage_ownership_inventory.v1",
        "inventory_id": document["inventory_id"],
        "inventory_version": document["inventory_version"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "manifest_ref": MANIFEST_PATH.as_posix(),
        "manifest_hash": document["content_hash"],
        "source_root": source_root_text,
        "module_count": len(rows),
        "active_import_module_count": len(active_graph),
        "coverage_module_count": len(coverage_files),
        "checks": checks,
        "historical_active_import_conflicts": historical_conflicts,
        "historical_deployment_conflicts": deployment_conflicts,
        "baseline": document["baseline"],
        "current_coverage": _coverage_totals(coverage),
        "scopes": scopes,
        "hotspots": {
            scope: _hotspots(rows, scope=scope, limit=20)
            for scope in sorted(ALLOWED_SCOPES)
        },
        "modules": rows,
        "content_included": False,
        "secret_included": False,
    }


def _validate_manifest(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != "ae.coverage_ownership.v1":
        raise AeCoverageOwnershipError("AE ownership manifest schema is invalid")
    content_hash = document.get("content_hash")
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in document.items() if key != "content_hash"}
    )
    if content_hash != expected:
        raise AeCoverageOwnershipError("AE ownership manifest hash is invalid")
    if document.get("inventory_version") != 1:
        raise AeCoverageOwnershipError("AE ownership inventory version is invalid")
    baseline = document.get("baseline")
    if not isinstance(baseline, Mapping):
        raise AeCoverageOwnershipError("AE coverage baseline is missing")
    for key in (
        "statements",
        "covered_statements",
        "branches",
        "covered_branches",
    ):
        value = baseline.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise AeCoverageOwnershipError(f"AE coverage baseline is invalid: {key}")


def _scope_overrides(
    document: Mapping[str, Any], *, root: Path, modules: set[str]
) -> dict[str, str]:
    values = document.get("scope_overrides")
    if not isinstance(values, list):
        raise AeCoverageOwnershipError("scope_overrides must be an array")
    result: dict[str, str] = {}
    for item in values:
        if not isinstance(item, Mapping):
            raise AeCoverageOwnershipError("scope override must be an object")
        path = _required_text(item, "path")
        scope = _required_text(item, "scope")
        _required_text(item, "rationale")
        if scope not in ALLOWED_SCOPES:
            raise AeCoverageOwnershipError(f"unknown AE ownership scope: {scope}")
        if path in result:
            raise AeCoverageOwnershipError(f"duplicate AE ownership override: {path}")
        if path not in modules or not (root / path).is_file():
            raise AeCoverageOwnershipError(f"AE ownership override is unavailable: {path}")
        result[path] = scope
    return result


def _quarantine_sources(
    root: Path, *, quarantine: Mapping[str, Any], source_root: str
) -> set[str]:
    values = quarantine.get("historical_assets")
    if not isinstance(values, list):
        raise AeCoverageOwnershipError("Golden A historical asset inventory is invalid")
    sources: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            raise AeCoverageOwnershipError("Golden A historical asset is invalid")
        path = _required_text(item, "path")
        digest = _required_text(item, "sha256")
        source = root / path
        if not source.is_file() or _file_hash(source) != digest:
            raise AeCoverageOwnershipError(
                f"Golden A historical asset hash has drifted: {path}"
            )
        if path.startswith(source_root + "/"):
            sources.add(path)
    if not sources:
        raise AeCoverageOwnershipError("Golden A historical source inventory is empty")
    return sources


def _deployment_conflicts(
    root: Path, *, inputs: list[str], historical_paths: set[str]
) -> list[dict[str, str]]:
    tokens = {
        path: (
            f"nex_ae_api.{Path(path).stem}",
            path,
        )
        for path in historical_paths
    }
    conflicts: list[dict[str, str]] = []
    for relative in inputs:
        path = root / relative
        if not path.is_file():
            raise AeCoverageOwnershipError(
                f"canonical deployment input is unavailable: {relative}"
            )
        source = path.read_text(encoding="utf-8")
        for historical, candidates in tokens.items():
            if any(candidate in source for candidate in candidates):
                conflicts.append({"input": relative, "historical_module": historical})
    return conflicts


def _coverage_files(
    coverage: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    if coverage is None:
        return {}
    values = coverage.get("files")
    if not isinstance(values, Mapping):
        raise AeCoverageOwnershipError("coverage files object is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for path, value in values.items():
        if isinstance(path, str) and isinstance(value, Mapping):
            summary = value.get("summary")
            if isinstance(summary, Mapping):
                result[path] = summary
    return result


def _module_row(
    path: str,
    *,
    scope: str,
    active_graph: set[str],
    coverage_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    summary = coverage_files.get(path)
    statements = _metric(summary, "num_statements")
    covered_statements = _metric(summary, "covered_lines")
    branches = _metric(summary, "num_branches")
    covered_branches = _metric(summary, "covered_branches")
    return {
        "path": path,
        "scope": scope,
        "active_import": path in active_graph,
        "coverage_present": summary is not None,
        "statements": statements,
        "covered_statements": covered_statements,
        "missing_statements": statements - covered_statements,
        "branches": branches,
        "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
    }


def _scope_summary(rows: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    selected = [row for row in rows if row["scope"] == scope]
    statements = sum(row["statements"] for row in selected)
    covered_statements = sum(row["covered_statements"] for row in selected)
    branches = sum(row["branches"] for row in selected)
    covered_branches = sum(row["covered_branches"] for row in selected)
    return {
        "module_count": len(selected),
        "active_import_module_count": sum(bool(row["active_import"]) for row in selected),
        "coverage_module_count": sum(bool(row["coverage_present"]) for row in selected),
        "statements": statements,
        "covered_statements": covered_statements,
        "missing_statements": statements - covered_statements,
        "statement_coverage": _percent(covered_statements, statements),
        "branches": branches,
        "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
        "branch_coverage": _percent(covered_branches, branches),
    }


def _hotspots(
    rows: list[dict[str, Any]], *, scope: str, limit: int
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in rows
        if row["scope"] == scope
        and (row["missing_statements"] or row["missing_branches"])
    ]
    selected.sort(
        key=lambda row: (
            -row["missing_statements"],
            -row["missing_branches"],
            row["path"],
        )
    )
    return selected[:limit]


def _coverage_totals(coverage: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if coverage is None:
        return None
    totals = coverage.get("totals")
    if not isinstance(totals, Mapping):
        raise AeCoverageOwnershipError("coverage totals object is invalid")
    return {
        "statements": _metric(totals, "num_statements"),
        "covered_statements": _metric(totals, "covered_lines"),
        "statement_coverage": totals.get("percent_statements_covered"),
        "branches": _metric(totals, "num_branches"),
        "covered_branches": _metric(totals, "covered_branches"),
        "branch_coverage": totals.get("percent_branches_covered"),
    }


def _metric(value: Mapping[str, Any] | None, key: str) -> int:
    if value is None:
        return 0
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise AeCoverageOwnershipError(f"coverage metric is invalid: {key}")
    return result


def _required_text(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise AeCoverageOwnershipError(f"required text is invalid: {key}")
    return result.strip()


def _required_string_list(value: Mapping[str, Any], key: str) -> list[str]:
    result = value.get(key)
    if not isinstance(result, list) or not result:
        raise AeCoverageOwnershipError(f"required string list is invalid: {key}")
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise AeCoverageOwnershipError(f"required string list is invalid: {key}")
    if len(set(result)) != len(result):
        raise AeCoverageOwnershipError(f"required string list has duplicates: {key}")
    return list(result)


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AeCoverageOwnershipError(f"JSON artifact must be an object: {path}")
    return value


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def summary_line(report: Mapping[str, Any]) -> str:
    scopes = report["scopes"]
    return (
        f"ae_coverage_ownership={report['status'].lower()} "
        f"modules={report['module_count']} "
        f"active_graph={report['active_import_module_count']} "
        f"product={scopes['ACTIVE_PRODUCT']['module_count']} "
        f"compatibility={scopes['ACTIVE_COMPATIBILITY']['module_count']} "
        f"historical={scopes['HISTORICAL_QUARANTINE']['module_count']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report the source-backed AE coverage ownership inventory"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = _json_object(ROOT / args.manifest)
        coverage = _json_object(ROOT / args.coverage) if args.coverage else None
        report = build_ownership_inventory(
            ROOT, manifest=manifest, coverage=coverage
        )
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            summary_line(report)
            if args.summary
            else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0 if report["status"] == "PASS" else 1
    except (OSError, json.JSONDecodeError, AeCoverageOwnershipError) as exc:
        print(f"ae_coverage_ownership=fail detail={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
