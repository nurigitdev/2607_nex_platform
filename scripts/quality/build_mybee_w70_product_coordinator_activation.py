#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "domains/mybee",
):
    sys.path.insert(0, str(source))

from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_coordinator_activation import (
    DEFAULT_ACTIVATION_PATH,
    DEFAULT_ROLLBACK_PATH,
    build_product_coordinator_activation_documents,
)


def main() -> int:
    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/"
                "ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )
    activation, rollback = build_product_coordinator_activation_documents(
        product_capabilities=capabilities,
        repository_root=ROOT,
    )
    for path, value in (
        (DEFAULT_ACTIVATION_PATH, activation),
        (DEFAULT_ROLLBACK_PATH, rollback),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "product_coordinator_activation=pass "
        f"activation_hash={activation['content_hash']} "
        f"rollback_hash={rollback['content_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
