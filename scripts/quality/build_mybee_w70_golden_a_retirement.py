#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
for source_root in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
):
    sys.path.insert(0, str(source_root))

from nex_ae_api.product_capability_retirements import (  # noqa: E402
    PRODUCT_CAPABILITY_RETIREMENT_SCHEMA_VERSION,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402

RETIREMENT_ROOT = Path("deployment/retirement")
INVENTORY_PATH = RETIREMENT_ROOT / "golden-a-reference-inventory.v1.json"
ROLLBACK_PATH = RETIREMENT_ROOT / "golden-a-rollback-receipt.v1.json"
PROJECTION_PATH = RETIREMENT_ROOT / "golden-a-selection-freeze.v1.json"

SCAN_ROOTS = (
    "apps",
    "contracts",
    "deployment",
    "docs/slices",
    "domains",
    "scripts",
    "services",
    "tests",
)
REFERENCE_PATTERNS = (
    r"golden[ _-]?a",
    r"FINANCE\.CREATE_VOUCHER_DRAFT",
    r"FINANCE\.VOUCHER_DRAFT_CREATE",
)
REFERENCE_RE = re.compile("|".join(REFERENCE_PATTERNS), re.IGNORECASE)

CONTROL_PATHS = {
    INVENTORY_PATH.as_posix(),
    ROLLBACK_PATH.as_posix(),
    PROJECTION_PATH.as_posix(),
    "docs/slices/mybee_phase1_w70_cp_m1_ga_ret_01.md",
    "scripts/quality/build_mybee_w70_golden_a_retirement.py",
    "scripts/quality/run_mybee_w70_golden_a_retirement_gate.py",
    "scripts/smoke/run_mybee_w70_golden_a_retirement_postgres.py",
    "services/nex-ae-api/nex_ae_api/product_capability_retirements.py",
    "tests/mybee_phase1/test_w70_cp_m1_ga_ret_01.py",
}

ROLLBACK_ARTIFACT_HASHES = {
    "deployment/environments/ae-product-capability-registry.v1.json": (
        "sha256:cb43b573d2e9284b79b10502a68b9a7f9fed2939b0a88db5c745b4c5396ec126"
    ),
    "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json": (
        "sha256:6ec6ce1b5d153799fed3dd36b5e213e33f1a2228dda1c407d08f81e4d236dfb1"
    ),
    "deployment/environments/finance-golden-a-vo00.v1.json": (
        "sha256:eb09eb09b589bbab5f61dc0c82555df2859efad7140566c248648fc20b43442f"
    ),
    "deployment/locks/ae-product-nsl-runtime-bundle.v1.json": (
        "sha256:f5f7ab97aaa5abc3642a734b153313b5af6c695790c4974a9d3b2ed8f897e27c"
    ),
    "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json": (
        "sha256:e05f4d4e06f52facf2f3b47602a68c63133384e72897f2e3ff9f492f03077283"
    ),
    "deployment/compose/canonical-platform.override.yaml": (
        "sha256:92169076ba81b602106980fd0e6d0deb6d3debcb3616f4def435d3b425361e29"
    ),
    "deployment/oci/canonical-platform-ae-runtime.Containerfile": (
        "sha256:0fa4adfd62b2a81a8d95fb57c6624cfdbdb3d59ffbf3aaa355d923f4fb608cbc"
    ),
    "reports/quality/mybee-w70-s8-01-foundation-gate.json": (
        "sha256:c5c16319783d5d11d23ea2b31d2a619f3c125d71523c4e5c6030e843652385ee"
    ),
    "scripts/quality/golden_journey_runners.v1.json": (
        "sha256:1a1461561c6552234ee4db50e1bf8fa9e67006f1f306b782bfc10f8da512ba82"
    ),
    "services/nex-ae-api/nex_ae_api/domain_intent_products.py": (
        "sha256:1de8e80b87d46c5800ae23ffde92b3d2d6a52b2d9678581a577ba6d25cfa1157"
    ),
    "services/nex-ae-api/nex_ae_api/product_runtime_profile.py": (
        "sha256:cddabe7078bb5a15ff53027b79fd389338eefa5dc839f29447b6b82900e8efd8"
    ),
}


def render_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def build_retirement_artifacts(root: Path) -> dict[Path, dict[str, Any]]:
    frozen = {}
    for relative in (INVENTORY_PATH, ROLLBACK_PATH, PROJECTION_PATH):
        path = root / relative
        if not path.is_file():
            break
        frozen[relative] = _json_object(path)
    if len(frozen) == 3:
        return frozen
    inventory = _build_inventory(root)
    inventory_bytes = render_json(inventory)
    rollback = _build_rollback_receipt(root)
    rollback_bytes = render_json(rollback)
    projection = _build_projection(
        root,
        inventory_sha256=_byte_digest(inventory_bytes),
        rollback_sha256=_byte_digest(rollback_bytes),
    )
    return {
        INVENTORY_PATH: inventory,
        ROLLBACK_PATH: rollback,
        PROJECTION_PATH: projection,
    }


def _build_inventory(root: Path) -> dict[str, Any]:
    paths = set(CONTROL_PATHS)
    for root_name in SCAN_ROOTS:
        scan_root = root / root_name
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or _ignored(path):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if REFERENCE_RE.search(source) or REFERENCE_RE.search(path.name):
                paths.add(path.relative_to(root).as_posix())
    entries = [
        {
            "path": path,
            "classification": _classification(path),
            "reason": _classification_reason(path),
        }
        for path in sorted(paths)
    ]
    counts = Counter(item["classification"] for item in entries)
    payload: dict[str, Any] = {
        "schema_version": "mybee.w70.golden_a_reference_inventory.v1",
        "inventory_id": "mybee-w70-golden-a-retirement",
        "inventory_version": 1,
        "frozen_at": "2026-11-15T00:00:00Z",
        "scan_roots": list(SCAN_ROOTS),
        "reference_patterns": list(REFERENCE_PATTERNS),
        "allowed_classifications": [
            "GENERALIZE",
            "HISTORY",
            "REMOVE_ACTIVE",
            "REPLAY_ONLY",
        ],
        "classification_counts": {
            key: counts.get(key, 0)
            for key in (
                "GENERALIZE",
                "HISTORY",
                "REMOVE_ACTIVE",
                "REPLAY_ONLY",
            )
        },
        "entries": entries,
    }
    payload["inventory_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_rollback_receipt(root: Path) -> dict[str, Any]:
    artifacts = []
    for relative, sha256 in ROLLBACK_ARTIFACT_HASHES.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"rollback artifact is unavailable: {relative}")
        artifacts.append({"path": relative, "sha256": sha256})
    payload: dict[str, Any] = {
        "schema_version": "mybee.w70.golden_a_rollback_receipt.v1",
        "receipt_id": "mybee-w70-golden-a-last-known-good",
        "receipt_version": 1,
        "captured_at": "2026-11-15T00:00:00Z",
        "valid_until": "2027-02-13T23:59:59Z",
        "invalidated_by": "CP-M1-GA-RET-02",
        "allowed_use": ["BOUNDED_ROLLBACK", "HISTORICAL_REPLAY"],
        "new_product_selection_allowed": False,
        "artifacts": artifacts,
    }
    payload["receipt_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_projection(
    root: Path,
    *,
    inventory_sha256: str,
    rollback_sha256: str,
) -> dict[str, Any]:
    registries = []
    for relative in (
        "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json",
        "deployment/environments/ae-product-capability-registry.v1.json",
    ):
        registry = _json_object(root / relative)
        registries.append(
            {
                "registry_id": registry["registry_id"],
                "registry_version": registry["registry_version"],
                "registry_hash": registry["registry_hash"],
            }
        )
    registries.sort(
        key=lambda item: (
            item["registry_id"],
            item["registry_version"],
            item["registry_hash"],
        )
    )
    retirement: dict[str, Any] = {
        "capability_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "capability_version": "1.1.0",
        "compatibility_aliases": sorted(
            (
                "FINANCE.VOUCHER_DRAFT.CREATE",
                "FINANCE.VOUCHER_DRAFT_CREATE",
                "createEosVoucherDraft",
            )
        ),
        "retirement_state": "REPLAY_ONLY",
        "new_selection": "DENY",
        "in_flight_policy": "DRAIN_OR_RECONCILE",
        "active_asset_policy": "RETAIN_UNTIL_RET_02",
        "reason_code": "W70_GOLDEN_A_PRODUCT_SELECTION_RETIRED",
    }
    retirement["retirement_hash"] = semantic_sha256_hash_ref(retirement)
    payload: dict[str, Any] = {
        "schema_version": PRODUCT_CAPABILITY_RETIREMENT_SCHEMA_VERSION,
        "projection_id": "mybee-w70-golden-a-selection-freeze",
        "projection_version": 1,
        "effective_at": "2026-11-15T00:00:00Z",
        "covered_registries": registries,
        "retirements": [retirement],
        "inventory_ref": {
            "path": INVENTORY_PATH.as_posix(),
            "sha256": inventory_sha256,
        },
        "rollback_receipt_ref": {
            "path": ROLLBACK_PATH.as_posix(),
            "sha256": rollback_sha256,
        },
    }
    payload["projection_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _classification(path: str) -> str:
    if path in CONTROL_PATHS:
        return "GENERALIZE"
    if path.startswith("docs/"):
        return "HISTORY"
    if path.startswith("deployment/locks/") or path.startswith(
        "deployment/releases/"
    ):
        return "REPLAY_ONLY"
    if path.startswith(("deployment/compose/", "deployment/environments/")):
        return "REMOVE_ACTIVE"
    if path.startswith("deployment/oci/"):
        return "REMOVE_ACTIVE"
    if path.startswith("contracts/"):
        return "REPLAY_ONLY" if "golden_a" in path else "GENERALIZE"
    if path.startswith("domains/"):
        return "GENERALIZE"
    if path.startswith("apps/"):
        return "REPLAY_ONLY"
    if path.startswith("tests/"):
        return "REPLAY_ONLY"
    if path.startswith("scripts/smoke/"):
        return "REPLAY_ONLY"
    if path.startswith("scripts/deployment/"):
        return "REMOVE_ACTIVE" if "canonical_platform" in path else "REPLAY_ONLY"
    if path.startswith("scripts/quality/"):
        return "REPLAY_ONLY"
    if path.startswith("services/nex-ae-api/"):
        return "REPLAY_ONLY" if "p8_demo" in path else "REMOVE_ACTIVE"
    if path.startswith("services/_shared/"):
        return "REPLAY_ONLY" if "golden_a" in path or "demo" in path else "GENERALIZE"
    if path.startswith("services/nex-eos/"):
        return "GENERALIZE"
    return "HISTORY"


def _classification_reason(path: str) -> str:
    classification = _classification(path)
    return {
        "GENERALIZE": "Reusable product contract or retirement control remains active.",
        "HISTORY": "Frozen design or Slice evidence remains immutable history.",
        "REMOVE_ACTIVE": "Active Golden A binding is removed after the replacement Gate.",
        "REPLAY_ONLY": "Artifact remains only for regression, audit, or historical replay.",
    }[classification]


def _ignored(path: Path) -> bool:
    return any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts)


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON artifact must be an object: {path}")
    return value


def _byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify W70 Golden A retirement artifacts."
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    artifacts = build_retirement_artifacts(ROOT)
    drift = []
    for relative, value in artifacts.items():
        expected = render_json(value)
        path = ROOT / relative
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
        elif not path.is_file() or path.read_bytes() != expected:
            drift.append(relative.as_posix())
    if drift:
        print("w70_golden_a_retirement=drift files=" + ",".join(drift))
        return 1
    print(
        "w70_golden_a_retirement=pass "
        f"mode={'write' if args.write else 'check'} artifacts={len(artifacts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
