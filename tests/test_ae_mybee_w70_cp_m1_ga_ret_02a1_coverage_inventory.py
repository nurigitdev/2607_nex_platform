from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from report_ae_coverage_ownership import (
    MANIFEST_PATH,
    AeCoverageOwnershipError,
    _quarantine_sources,
    build_ownership_inventory,
    summary_line,
)

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _rehash(document: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(document)
    result["content_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in result.items() if key != "content_hash"}
    )
    return result


def _expected_inventory_counts(manifest: dict[str, object]) -> dict[str, int]:
    source_root = manifest["source_root"]
    assert isinstance(source_root, str)
    modules = tuple((ROOT / source_root).rglob("*.py"))
    overrides = manifest["scope_overrides"]
    assert isinstance(overrides, list)
    compatibility_count = sum(
        item["scope"] == "ACTIVE_COMPATIBILITY" for item in overrides
    )
    historical_count = sum(
        item["scope"] == "HISTORICAL_QUARANTINE" for item in overrides
    )
    return {
        "module_count": len(modules),
        "product_count": len(modules) - compatibility_count - historical_count,
        "compatibility_count": compatibility_count,
        "historical_count": historical_count,
    }


def test_real_inventory_classifies_every_ae_module_and_freezes_baseline() -> None:
    manifest = _json(ROOT / MANIFEST_PATH)
    expected = _expected_inventory_counts(manifest)
    report = build_ownership_inventory(
        ROOT,
        manifest=manifest,
    )

    assert report["status"] == "PASS"
    assert report["module_count"] == expected["module_count"]
    assert report["active_import_module_count"] == 96
    assert report["coverage_module_count"] == 0
    assert report["checks"] == {
        "manifest_hash_valid": True,
        "all_modules_classified": True,
        "historical_scope_matches_quarantine": True,
        "historical_hashes_match": True,
        "historical_absent_from_active_graph": True,
        "historical_absent_from_deployment_inputs": True,
        "coverage_inventory_complete": True,
    }
    assert {
        scope: value["module_count"] for scope, value in report["scopes"].items()
    } == {
        "ACTIVE_PRODUCT": expected["product_count"],
        "ACTIVE_COMPATIBILITY": expected["compatibility_count"],
        "HISTORICAL_QUARANTINE": expected["historical_count"],
    }
    assert report["scopes"]["ACTIVE_PRODUCT"]["active_import_module_count"] == 96
    assert report["scopes"]["ACTIVE_COMPATIBILITY"]["active_import_module_count"] == 0
    assert report["scopes"]["HISTORICAL_QUARANTINE"]["active_import_module_count"] == 0
    assert report["current_coverage"] is None
    assert manifest["baseline"] == {
        "slice": "CP-M1-GA-RET-02A.0",
        "source_commit": "46de02aa",
        "coverage_ref": "reports/quality/mybee-w70-ga-ret-02a0-ae.coverage.json",
        "statements": 39011,
        "covered_statements": 37411,
        "statement_coverage": 95.89859270462178,
        "branches": 12404,
        "covered_branches": 11666,
        "branch_coverage": 94.05030635278942,
        "canonical_statement_floor": 95.0,
        "canonical_branch_floor": 94.0,
        "ret02a_statement_target": 96.25,
        "ret02a_branch_target": 94.5,
    }
    assert len({item["path"] for item in report["modules"]}) == expected["module_count"]
    assert summary_line(report) == (
        f"ae_coverage_ownership=pass modules={expected['module_count']} "
        f"active_graph=96 product={expected['product_count']} "
        f"compatibility={expected['compatibility_count']} "
        f"historical={expected['historical_count']} coverage=not-provided "
        "conflicts=0"
    )


def test_inventory_fails_closed_on_manifest_hash_or_scope_drift() -> None:
    manifest = _json(ROOT / MANIFEST_PATH)
    tampered = copy.deepcopy(manifest)
    tampered["default_scope"] = "ACTIVE_COMPATIBILITY"
    with pytest.raises(AeCoverageOwnershipError, match="manifest hash"):
        build_ownership_inventory(ROOT, manifest=tampered)

    invalid_scope = copy.deepcopy(manifest)
    invalid_scope["scope_overrides"][0]["scope"] = "UNKNOWN"
    invalid_scope = _rehash(invalid_scope)
    with pytest.raises(AeCoverageOwnershipError, match="unknown AE ownership scope"):
        build_ownership_inventory(ROOT, manifest=invalid_scope)


def test_inventory_requires_exact_quarantine_and_existing_overrides() -> None:
    manifest = _json(ROOT / MANIFEST_PATH)
    missing_historical = copy.deepcopy(manifest)
    missing_historical["scope_overrides"] = [
        item
        for item in missing_historical["scope_overrides"]
        if item["path"] != "services/nex-ae-api/nex_ae_api/domain_intent_products.py"
    ]
    missing_historical = _rehash(missing_historical)
    with pytest.raises(AeCoverageOwnershipError, match="hash-pinned quarantine"):
        build_ownership_inventory(ROOT, manifest=missing_historical)

    unavailable = copy.deepcopy(manifest)
    unavailable["scope_overrides"][0]["path"] = (
        "services/nex-ae-api/nex_ae_api/not_a_module.py"
    )
    unavailable = _rehash(unavailable)
    with pytest.raises(AeCoverageOwnershipError, match="override is unavailable"):
        build_ownership_inventory(ROOT, manifest=unavailable)


def test_inventory_detects_historical_deployment_binding_without_executing_it() -> None:
    manifest = _json(ROOT / MANIFEST_PATH)
    manifest["canonical_deployment_inputs"] = [
        *manifest["canonical_deployment_inputs"],
        "services/nex-ae-api/nex_ae_api/product_controlled_skill.py",
    ]
    manifest = _rehash(manifest)

    report = build_ownership_inventory(ROOT, manifest=manifest)

    assert report["status"] == "FAIL"
    assert report["checks"]["historical_absent_from_deployment_inputs"] is False
    assert report["historical_deployment_conflicts"] == [
        {
            "input": "services/nex-ae-api/nex_ae_api/product_controlled_skill.py",
            "historical_module": (
                "services/nex-ae-api/nex_ae_api/golden_a_planning.py"
            ),
        }
    ]


def test_inventory_rejects_quarantine_hash_and_coverage_metric_drift() -> None:
    quarantine = _json(
        ROOT / "deployment/retirement/golden-a-historical-quarantine.v1.json"
    )
    quarantine["historical_assets"][0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(AeCoverageOwnershipError, match="hash has drifted"):
        _quarantine_sources(
            ROOT,
            quarantine=quarantine,
            source_root="services/nex-ae-api/nex_ae_api",
        )

    coverage = {
        "files": {},
        "totals": {
            "num_statements": "39011",
            "covered_lines": 1,
            "percent_statements_covered": 100.0,
            "num_branches": 0,
            "covered_branches": 0,
            "percent_branches_covered": 100.0,
        },
    }
    with pytest.raises(AeCoverageOwnershipError, match="coverage metric"):
        build_ownership_inventory(
            ROOT, manifest=_json(ROOT / MANIFEST_PATH), coverage=coverage
        )


def test_inventory_fails_gate_when_coverage_omits_owned_modules() -> None:
    manifest = _json(ROOT / MANIFEST_PATH)
    expected = _expected_inventory_counts(manifest)
    optional_paths = manifest["coverage_optional_paths"]
    assert isinstance(optional_paths, list)
    coverage = {
        "files": {},
        "totals": {
            "num_statements": 0,
            "covered_lines": 0,
            "percent_statements_covered": 100.0,
            "num_branches": 0,
            "covered_branches": 0,
            "percent_branches_covered": 100.0,
        },
    }

    report = build_ownership_inventory(ROOT, manifest=manifest, coverage=coverage)

    assert report["status"] == "FAIL"
    assert report["checks"]["coverage_inventory_complete"] is False
    assert len(report["coverage_unreported_modules"]) == (
        expected["module_count"] - len(optional_paths)
    )
    assert (
        "services/nex-ae-api/nex_ae_api/__init__.py"
        not in report["coverage_unreported_modules"]
    )


def test_inventory_cli_writes_generated_evidence(tmp_path: Path) -> None:
    output = tmp_path / "inventory.json"
    completed = subprocess.run(
        (
            sys.executable,
            "scripts/quality/report_ae_coverage_ownership.py",
            "--output",
            output.as_posix(),
            "--summary",
        ),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip().startswith("ae_coverage_ownership=pass")
    assert _json(output)["status"] == "PASS"
