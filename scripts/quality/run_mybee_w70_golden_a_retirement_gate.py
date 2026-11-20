#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for source_root in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "scripts/quality",
):
    sys.path.insert(0, str(source_root))

from build_mybee_w70_golden_a_retirement import (
    INVENTORY_PATH,
    PROJECTION_PATH,
    ROLLBACK_PATH,
    build_retirement_artifacts,
    render_json,
)
from nex_ae_api.domain_intent_products import (
    build_domain_intent_activator_registry,
)
from nex_ae_api.golden_a_planning import GOLDEN_A_CAPABILITY_ID
from nex_ae_api.product_capabilities import (
    PRODUCT_CAPABILITY_REGISTRY_PATH_ENV,
    load_product_capability_registry,
)
from nex_ae_api.product_capability_retirements import (
    PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV,
    load_product_capability_retirement_projection,
)

AUTHORITY_ENV = "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH"


def run_gate(root: Path = ROOT) -> dict[str, Any]:
    expected = build_retirement_artifacts(root)
    exact = all(
        (root / relative).is_file()
        and (root / relative).read_bytes() == render_json(value)
        for relative, value in expected.items()
    )
    projection = load_product_capability_retirement_projection(
        {PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(root / PROJECTION_PATH)},
        required=True,
    )
    v1 = load_product_capability_registry(
        {
            PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(
                root / "deployment/environments/ae-product-capability-registry.v1.json"
            )
        }
    )
    m1 = load_product_capability_registry(
        {
            PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(
                root
                / "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json"
            )
        }
    )
    selected_v1 = projection.selectable_registry(v1)
    selected_m1 = projection.selectable_registry(m1)
    product_environ = {
        "NEX_DEPLOYMENT_BOUNDARY": "CANONICAL_PLATFORM",
        PRODUCT_CAPABILITY_REGISTRY_PATH_ENV: str(
            root / "deployment/environments/ae-product-capability-registry.v1.json"
        ),
        PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV: str(root / PROJECTION_PATH),
        AUTHORITY_ENV: str(
            root / "deployment/environments/finance-golden-a-vo00.v1.json"
        ),
    }
    public_activators = build_domain_intent_activator_registry(product_environ)
    replay_activators = build_domain_intent_activator_registry(
        product_environ, include_replay_only=True
    )
    inventory = _json(root / INVENTORY_PATH)
    rollback = _json(root / ROLLBACK_PATH)
    compose = (
        root / "deployment/compose/canonical-platform.override.yaml"
    ).read_text(encoding="utf-8")
    containerfile = (
        root / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")
    checks = {
        "retirement_artifacts_exact": exact,
        "projection_blocks_golden_a_and_aliases": all(
            projection.is_new_selection_denied(identity)
            for identity in (
                GOLDEN_A_CAPABILITY_ID,
                "FINANCE.VOUCHER_DRAFT.CREATE",
                "FINANCE.VOUCHER_DRAFT_CREATE",
                "createEosVoucherDraft",
            )
        ),
        "v1_new_selection_empty": selected_v1.registrations == (),
        "m1_new_selection_keeps_only_d04_d12": {
            item.capability_id for item in selected_m1.registrations
        }
        == {
            "FINANCE.VOUCHER.APPROVE_AND_POST",
            "PROJECT.WORK_CODE_SET.GET",
        },
        "public_activator_removed": public_activators.registrations == (),
        "replay_activator_retained": (
            replay_activators.resolve(GOLDEN_A_CAPABILITY_ID) is not None
        ),
        "inventory_has_only_admitted_classifications": (
            len(inventory["entries"])
            == sum(inventory["classification_counts"].values())
            and set(inventory["classification_counts"])
            == {"GENERALIZE", "HISTORY", "REMOVE_ACTIVE", "REPLAY_ONLY"}
        ),
        "rollback_is_bounded_and_non_selectable": (
            rollback["invalidated_by"] == "CP-M1-GA-RET-02"
            and rollback["new_product_selection_allowed"] is False
            and len(rollback["artifacts"]) >= 10
        ),
        "canonical_compose_has_completed_retirement": (
            PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV not in compose
            and "ae-product-capability-registry.mybee-m1.v3.json" in compose
        ),
        "canonical_image_has_completed_retirement": (
            PRODUCT_CAPABILITY_RETIREMENT_PATH_ENV not in containerfile
            and "ae-mybee-m1-runtime-activation.v3.json" in containerfile
        ),
    }
    return {
        "schema_version": "mybee.w70.golden_a_retirement_gate.v1",
        "slice": "CP-M1-GA-RET-01",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "projection_hash": projection.projection_hash,
        "inventory_hash": inventory["inventory_hash"],
        "rollback_receipt_hash": rollback["receipt_hash"],
        "reference_count": len(inventory["entries"]),
        "content_included": False,
        "secret_included": False,
    }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the W70 Golden A new-selection retirement Gate."
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
            "w70_golden_a_retirement_gate="
            f"{result['status'].lower()} references={result['reference_count']}"
        )
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
