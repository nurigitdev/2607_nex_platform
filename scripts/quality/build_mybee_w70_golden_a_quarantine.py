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
sys.path.insert(0, str(ROOT / "services/_shared"))

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

LEGACY_REGISTRY = Path(
    "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json"
)
REGISTRY_PATH = Path(
    "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
)
LEGACY_ADMISSION = Path("deployment/locks/ae-mybee-m1-runtime-admission.v1.json")
ADMISSION_PATH = Path("deployment/locks/ae-mybee-m1-runtime-admission.v2.json")
ROLLBACK_PATH = Path("deployment/locks/ae-mybee-m1-generalized-rollback.v1.json")
ACTIVATION_PATH = Path("deployment/locks/ae-mybee-m1-runtime-activation.v2.json")
QUARANTINE_PATH = Path("deployment/retirement/golden-a-historical-quarantine.v1.json")

GOLDEN_A_CAPABILITY_ID = "FINANCE.CREATE_VOUCHER_DRAFT"
ACTIVE_CAPABILITIES = (
    "FINANCE.VOUCHER.APPROVE_AND_POST",
    "PROJECT.WORK_CODE_SET.GET",
)
HISTORICAL_ASSETS = (
    "deployment/environments/ae-product-capability-registry.v1.json",
    LEGACY_REGISTRY.as_posix(),
    "deployment/environments/finance-golden-a-vo00.v1.json",
    "deployment/locks/ae-product-nsl-runtime-bundle.v1.json",
    LEGACY_ADMISSION.as_posix(),
    "deployment/locks/ae-mybee-m1-runtime-activation.v1.json",
    "deployment/retirement/golden-a-reference-inventory.v1.json",
    "deployment/retirement/golden-a-rollback-receipt.v1.json",
    "deployment/retirement/golden-a-selection-freeze.v1.json",
    "services/nex-ae-api/nex_ae_api/domain_intent_products.py",
    "services/nex-ae-api/nex_ae_api/finance_golden_a_activation.py",
    "services/nex-ae-api/nex_ae_api/golden_a_planning.py",
    "services/nex-ae-api/nex_ae_api/mybee_product_consumer.py",
    "services/nex-ae-api/nex_ae_api/product_controlled_skill.py",
)


def render_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def build_quarantine_artifacts(root: Path) -> dict[Path, dict[str, Any]]:
    registry = _build_registry(root)
    admission = _build_admission(root, registry)
    rollback = _build_rollback(admission, registry)
    rollback_bytes = render_json(rollback)
    activation = _build_activation(
        root,
        admission=admission,
        registry=registry,
        rollback=rollback,
        rollback_sha256=_byte_digest(rollback_bytes),
    )
    quarantine = _build_quarantine(
        root,
        registry=registry,
        admission=admission,
        activation=activation,
        rollback=rollback,
    )
    return {
        REGISTRY_PATH: registry,
        ADMISSION_PATH: admission,
        ROLLBACK_PATH: rollback,
        ACTIVATION_PATH: activation,
        QUARANTINE_PATH: quarantine,
    }


def _build_registry(root: Path) -> dict[str, Any]:
    source = _json_object(root / LEGACY_REGISTRY)
    registrations = [
        item
        for item in source["registrations"]
        if item["capability"]["capability_id"] != GOLDEN_A_CAPABILITY_ID
    ]
    capabilities = tuple(item["capability"]["capability_id"] for item in registrations)
    if capabilities != ACTIVE_CAPABILITIES:
        raise RuntimeError("successor capability set has drifted")
    payload: dict[str, Any] = {
        "schema_version": source["schema_version"],
        "registry_id": source["registry_id"],
        "registry_version": 4,
        "registrations": registrations,
    }
    payload["registry_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_admission(root: Path, registry: Mapping[str, Any]) -> dict[str, Any]:
    source = _json_object(root / LEGACY_ADMISSION)
    payload = {key: value for key, value in source.items() if key != "content_hash"}
    payload.update(
        capability_registry_id=registry["registry_id"],
        capability_registry_version=registry["registry_version"],
        capability_registry_hash=registry["registry_hash"],
        runtime_selectable_capabilities=list(ACTIVE_CAPABILITIES),
    )
    payload["content_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_rollback(
    admission: Mapping[str, Any], registry: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "ae.generalized_runtime_rollback_receipt.v1",
        "receipt_id": "mybee-m1-last-admitted-generalized-release",
        "receipt_version": 1,
        "captured_at": "2026-11-16T00:00:00Z",
        "runtime_profile": "VERIFIED_PRODUCT_RELEASE",
        "runtime_admission_ref": ADMISSION_PATH.as_posix(),
        "runtime_admission_hash": admission["content_hash"],
        "product_registry_ref": REGISTRY_PATH.as_posix(),
        "product_registry_hash": registry["registry_hash"],
        "signed_release_ref": (
            "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
        ),
        "signed_release_hash": admission["release_hash"],
        "runtime_selectable_capabilities": list(ACTIVE_CAPABILITIES),
        "golden_a_dependency": False,
        "allowed_use": ["CONTROLLED_ROLLBACK", "RESTART_RECOVERY"],
    }
    payload["content_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_activation(
    root: Path,
    *,
    admission: Mapping[str, Any],
    registry: Mapping[str, Any],
    rollback: Mapping[str, Any],
    rollback_sha256: str,
) -> dict[str, Any]:
    release = _json_object(
        root / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
    )
    payload: dict[str, Any] = {
        "schema_version": "ae.verified_product_runtime_activation.v2",
        "decision_id": "CP-M1-GA-RET-02",
        "decided_at": "2026-11-16T00:00:00Z",
        "activation_state": "ACTIVE_GENERALIZED",
        "runtime_profile": "VERIFIED_PRODUCT_RELEASE",
        "runtime_admission_ref": ADMISSION_PATH.as_posix(),
        "runtime_admission_hash": admission["content_hash"],
        "signed_release_ref": (
            "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
        ),
        "signed_release_hash": release["content_hash"],
        "product_registry_ref": REGISTRY_PATH.as_posix(),
        "product_registry_hash": registry["registry_hash"],
        "runtime_selectable_capabilities": list(ACTIVE_CAPABILITIES),
        "rollback_target": {
            "profile": "VERIFIED_PRODUCT_RELEASE",
            "receipt_ref": ROLLBACK_PATH.as_posix(),
            "receipt_sha256": rollback_sha256,
            "runtime_admission_hash": rollback["runtime_admission_hash"],
            "golden_a_dependency": False,
        },
        "readiness": {
            "exact_signed_release_required": True,
            "exact_registry_required": True,
            "exact_operation_registry_required": True,
            "actual_postgresql_gate_required": True,
            "remote_provider_required": False,
        },
    }
    payload["content_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _build_quarantine(
    root: Path,
    *,
    registry: Mapping[str, Any],
    admission: Mapping[str, Any],
    activation: Mapping[str, Any],
    rollback: Mapping[str, Any],
) -> dict[str, Any]:
    historical_assets = []
    for relative in HISTORICAL_ASSETS:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"historical Golden A asset is unavailable: {relative}")
        historical_assets.append({"path": relative, "sha256": _file_digest(path)})
    payload: dict[str, Any] = {
        "schema_version": "mybee.w70.golden_a_historical_quarantine.v1",
        "quarantine_id": "mybee-w70-golden-a-historical-quarantine",
        "quarantine_version": 1,
        "effective_at": "2026-11-16T00:00:00Z",
        "active_selection": {
            "registry_ref": REGISTRY_PATH.as_posix(),
            "registry_hash": registry["registry_hash"],
            "admission_ref": ADMISSION_PATH.as_posix(),
            "admission_hash": admission["content_hash"],
            "activation_ref": ACTIVATION_PATH.as_posix(),
            "activation_hash": activation["content_hash"],
            "rollback_ref": ROLLBACK_PATH.as_posix(),
            "rollback_hash": rollback["content_hash"],
            "runtime_selectable_capabilities": list(ACTIVE_CAPABILITIES),
        },
        "historical_assets": historical_assets,
        "historical_policy": {
            "new_selection": "DENY",
            "active_runtime_import": "DENY",
            "canonical_image_packaging": "DENY",
            "execution": "OFFLINE_REPLAY_ONLY",
            "database_cleanup": "DENY",
        },
        "deprecated_api_aliases_retained": [
            "FINANCE.VOUCHER_DRAFT.CREATE",
            "FINANCE.VOUCHER_DRAFT_CREATE",
            "createEosVoucherDraft",
        ],
        "database_migration_required": False,
        "remote_provider_required": False,
    }
    payload["content_hash"] = semantic_sha256_hash_ref(payload)
    return payload


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON artifact must be an object: {path}")
    return value


def _byte_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _file_digest(path: Path) -> str:
    return _byte_digest(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify W70 Golden A quarantine artifacts."
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    artifacts = build_quarantine_artifacts(ROOT)
    drift: list[str] = []
    for relative, value in artifacts.items():
        expected = render_json(value)
        path = ROOT / relative
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
        elif not path.is_file() or path.read_bytes() != expected:
            drift.append(relative.as_posix())
    if drift:
        print("w70_golden_a_quarantine=drift files=" + ",".join(drift))
        return 1
    print(
        "w70_golden_a_quarantine=pass "
        f"mode={'write' if args.write else 'check'} artifacts={len(artifacts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
