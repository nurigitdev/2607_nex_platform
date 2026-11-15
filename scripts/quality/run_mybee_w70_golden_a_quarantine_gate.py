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
for source_root in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "domains/mybee",
    ROOT / "scripts/quality",
):
    sys.path.insert(0, str(source_root))

from build_mybee_w70_golden_a_quarantine import (
    ACTIVATION_PATH,
    ACTIVE_CAPABILITIES,
    ADMISSION_PATH,
    QUARANTINE_PATH,
    REGISTRY_PATH,
    ROLLBACK_PATH,
    build_quarantine_artifacts,
    render_json,
)
from nex_ae_api.mybee_m1_skill_runtime import (
    build_mybee_m1_runtime_admission,
)
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_ae_api.prompts import (
    AE_INTENT_RESOLUTION_BINDING,
    AE_PROMPT_SEEDS,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ACTIVE_SOURCE_PATHS = (
    "deployment/compose/canonical-platform.override.yaml",
    "deployment/oci/canonical-platform-ae-runtime.Containerfile",
    "scripts/deployment/build_canonical_platform_ae_runtime_image.py",
    "services/nex-ae-api/nex_ae_api/agent_runtime_process.py",
    "services/nex-ae-api/nex_ae_api/product_runtime_profile.py",
    "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py",
)
FORBIDDEN_ACTIVE_TOKENS = (
    "FINANCE.CREATE_VOUCHER_DRAFT",
    "FINANCE.VOUCHER_DRAFT_CREATE",
    "GOLDEN_A_ROLLBACK",
    "finance-golden-a",
    "golden-a-selection-freeze",
    "golden-a-rollback-receipt",
    "NEX_AE_NSL_BUNDLE_MANIFEST",
    "NEX_AE_NSL_SKILL_ROOT",
)


def run_gate(root: Path = ROOT) -> dict[str, Any]:
    expected = build_quarantine_artifacts(root)
    exact = all(
        (root / relative).is_file()
        and (root / relative).read_bytes() == render_json(value)
        for relative, value in expected.items()
    )
    registry = load_product_capability_registry(
        {PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(root / REGISTRY_PATH)}
    )
    admission = _json(root / ADMISSION_PATH)
    activation = _json(root / ACTIVATION_PATH)
    rollback = _json(root / ROLLBACK_PATH)
    quarantine = _json(root / QUARANTINE_PATH)
    environ = {
        PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(root / REGISTRY_PATH),
        "NEX_AE_M1_REPOSITORY_ROOT": str(root),
        "NEX_AE_M1_SIGNED_SKILL_LOCK": str(
            root / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
        ),
    }
    active_sources = {
        relative: (root / relative).read_text(encoding="utf-8")
        for relative in ACTIVE_SOURCE_PATHS
    }
    prompt = next(
        item
        for item in AE_PROMPT_SEEDS
        if item.binding_key == AE_INTENT_RESOLUTION_BINDING
    )
    historical_assets = quarantine.get("historical_assets")
    checks = {
        "successor_artifacts_exact": exact,
        "active_registry_is_d04_d12_only": tuple(
            item.capability_id for item in registry.registrations
        )
        == ACTIVE_CAPABILITIES,
        "runtime_admission_rebuilds_exactly": (
            build_mybee_m1_runtime_admission(environ) == admission
        ),
        "activation_is_generalized": (
            activation.get("activation_state") == "ACTIVE_GENERALIZED"
            and activation.get("runtime_profile") == "VERIFIED_PRODUCT_RELEASE"
            and activation.get("rollback_target", {}).get("golden_a_dependency")
            is False
        ),
        "rollback_is_generalized": (
            rollback.get("golden_a_dependency") is False
            and tuple(rollback.get("runtime_selectable_capabilities") or ())
            == ACTIVE_CAPABILITIES
        ),
        "active_sources_have_no_golden_binding": not any(
            token in source
            for source in active_sources.values()
            for token in FORBIDDEN_ACTIVE_TOKENS
        ),
        "active_import_graph_is_generic": (
            "mybee_product_consumer"
            not in active_sources[
                "services/nex-ae-api/nex_ae_api/agent_runtime_process.py"
            ]
            and "domain_intent_products"
            not in active_sources[
                "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py"
            ]
            and "product_controlled_skill"
            not in active_sources[
                "services/nex-ae-api/nex_ae_api/product_runtime_profile.py"
            ]
        ),
        "active_prompt_is_v9_and_scenario_free": (
            prompt.version == "v9"
            and "FINANCE.CREATE_VOUCHER_DRAFT" not in prompt.content
            and "golden_a" not in json.dumps(prompt.metadata, sort_keys=True).lower()
            and "FINANCE.VOUCHER.APPROVE_AND_POST" in prompt.content
        ),
        "historical_assets_are_hash_pinned": (
            isinstance(historical_assets, list)
            and len(historical_assets) >= 10
            and all(_historical_asset_matches(root, item) for item in historical_assets)
        ),
        "quarantine_hash_is_valid": (
            quarantine.get("content_hash")
            == semantic_sha256_hash_ref(
                {
                    key: value
                    for key, value in quarantine.items()
                    if key != "content_hash"
                }
            )
        ),
        "database_and_provider_scope_unchanged": (
            quarantine.get("database_migration_required") is False
            and quarantine.get("remote_provider_required") is False
        ),
    }
    return {
        "schema_version": "mybee.w70.golden_a_quarantine_gate.v1",
        "slice": "CP-M1-GA-RET-02",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "active_capabilities": list(ACTIVE_CAPABILITIES),
        "registry_hash": registry.registry_hash,
        "admission_hash": admission["content_hash"],
        "activation_hash": activation["content_hash"],
        "quarantine_hash": quarantine["content_hash"],
        "historical_asset_count": len(historical_assets or ()),
        "content_included": False,
        "secret_included": False,
    }


def _historical_asset_matches(root: Path, value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    relative = value.get("path")
    expected = value.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected, str):
        return False
    path = root / relative
    return path.is_file() and expected == (
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    )


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the W70 Golden A active-binding removal Gate."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_gate()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.summary:
        print(
            "w70_golden_a_quarantine_gate="
            f"{result['status'].lower()} "
            f"active={len(result['active_capabilities'])} "
            f"history={result['historical_asset_count']}"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
