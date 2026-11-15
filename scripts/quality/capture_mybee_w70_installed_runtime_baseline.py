#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "deployment/audits/mybee-w70-e2e-fx-01a1-baseline.v1.json"

SOURCE_COMPONENTS = (
    ("claim_handoff", "services/nex-ae-api/nex_ae_api/claim_handoff_api.py", "DURABLE_ADMISSION_ONLY", "BACKGROUND_PLANNING_AND_SCHEDULING_NOT_COMPOSED"),
    ("background_planning", "services/nex-ae-api/nex_ae_api/background_planning.py", "IMPLEMENTED_COMPONENT", "NOT_INSTALLED_AT_HANDOFF_BOUNDARY"),
    ("installed_worker", "services/nex-ae-api/nex_ae_api/agent_runtime_process.py", "GENERIC_WORKER_WITH_PRODUCT_PROFILE", "PRODUCT_PROFILE_IS_SINGLE_SKILL"),
    ("product_executor_profile", "services/nex-ae-api/nex_ae_api/product_runtime_profile.py", "GOLDEN_A_SINGLE_SKILL", "MULTI_SKILL_RELEASE_SELECTION_MISSING"),
    ("product_consumer", "services/nex-ae-api/nex_ae_api/mybee_product_consumer.py", "GOLDEN_A_FIXED_CAPABILITY", "GENERIC_OPERATION_REGISTRY_MISSING"),
    ("signed_release", "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json", "SIGNED_D04_D12_ADMITTED", "NOT_INSTALLED_IN_CANONICAL_RUNTIME"),
    ("mixed_registry", "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json", "IMMUTABLE_MIXED_CHECKPOINT", "SUCCESSOR_ACTIVE_RELEASE_REQUIRED"),
    ("canonical_compose", "deployment/compose/canonical-platform.override.yaml", "GOLDEN_A_ASSETS_STILL_PACKAGED_FOR_ROLLBACK", "M1_RELEASE_INPUTS_NOT_PROMOTED"),
)

DATA_ORIGINS = (
    ("tenant_requester", "OA_AUTHENTICATED_SESSION", "FIXED_PRINCIPAL"),
    ("project_code", "EOS_PROJECT_RESOLUTION_AND_OA_ENTITLEMENT", "MODEL_OR_FIXTURE"),
    ("project_agent", "AE_SYNCHRONIZED_PROJECT_AGENT", "SCENARIO_AGENT_ID"),
    ("work_item_claim", "WC_WORK_ITEM_CLAIM_ASSIGNMENT", "RUNNER_STATE_MUTATION"),
    ("planning_source", "AE_DURABLE_CLAIMED_WORK_SOURCE", "SMOKE_PAYLOAD_SHORTCUT"),
    ("capability", "PRODUCT_CAPABILITY_REGISTRY", "PROMPT_OR_FILENAME"),
    ("skill", "SIGNED_RELEASE_EXACT_SKILL", "DIRECTORY_ORDER"),
    ("business_authority", "OA_WC_EOS_POSTGRESQL_SOR", "FIXTURE_SUCCESS"),
    ("runtime_state", "AE_EXECUTION_PLAN_JOB_TABLES", "RUNNER_INSERT_UPDATE"),
    ("result", "AE_WC_EOS_WA_DURABLE_TRANSITIONS", "FABRICATED_WORK_RESULT"),
)

RESIDUE_PATTERNS = (
    "FINANCE.CREATE_VOUCHER_DRAFT",
    "golden_a",
    "p8_demo",
    "NEX_AE_DEMO_",
    "NEX_*_FIXTURE",
)


def build_baseline(root: Path = ROOT) -> dict[str, Any]:
    components = []
    for component_id, relative, current_state, gap in SOURCE_COMPONENTS:
        path = root / relative
        components.append(
            {
                "component_id": component_id,
                "path": relative,
                "sha256": _digest(path.read_bytes()),
                "current_state": current_state,
                "gap": gap,
            }
        )
    residue = []
    for item in components:
        path = root / item["path"]
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = sorted(pattern for pattern in RESIDUE_PATTERNS if pattern in source)
        if hits:
            residue.append({"path": item["path"], "patterns": hits})
    payload: dict[str, Any] = {
        "schema_version": "mybee.w70.installed_runtime_baseline.v1",
        "slice": "CP-M1-E2E-FX-01A.1",
        "captured_at": "2026-11-15T00:00:00Z",
        "database_migration": False,
        "remote_provider_required": False,
        "data_origin_matrix": [
            {
                "runtime_value": runtime_value,
                "authoritative_origin": origin,
                "prohibited_substitute": prohibited,
            }
            for runtime_value, origin, prohibited in DATA_ORIGINS
        ],
        "installed_composition": components,
        "residue_baseline": residue,
        "closure_state": "BASELINE_CAPTURED_IMPLEMENTATION_OPEN",
        "next_boundary": "CP-M1-E2E-FX-01A.2",
    }
    payload["content_hash"] = _semantic_hash(payload)
    return payload


def validate_baseline(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("installed runtime baseline must be an object")
    required = {
        "schema_version", "slice", "captured_at", "database_migration",
        "remote_provider_required", "data_origin_matrix", "installed_composition",
        "residue_baseline", "closure_state", "next_boundary", "content_hash",
    }
    if set(value) != required:
        raise ValueError("installed runtime baseline fields differ")
    expected = _semantic_hash(
        {key: item for key, item in value.items() if key != "content_hash"}
    )
    if value["content_hash"] != expected:
        raise ValueError("installed runtime baseline hash differs")
    if value["schema_version"] != "mybee.w70.installed_runtime_baseline.v1":
        raise ValueError("installed runtime baseline schema differs")
    if len(value["data_origin_matrix"]) != len(DATA_ORIGINS):
        raise ValueError("installed runtime data-origin matrix is incomplete")
    if len(value["installed_composition"]) != len(SOURCE_COMPONENTS):
        raise ValueError("installed runtime composition map is incomplete")
    return value


def _semantic_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return _digest(encoded)


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _render(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture the immutable W70 installed-runtime entry baseline."
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    if args.validate is not None:
        validate_baseline(json.loads(args.validate.read_text(encoding="utf-8")))
        print("w70_e2e_fx_01a1_baseline=pass mode=validate")
        return 0
    expected = _render(build_baseline())
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(expected, encoding="utf-8")
    elif not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
        print("w70_e2e_fx_01a1_baseline=drift")
        return 1
    print(
        "w70_e2e_fx_01a1_baseline=pass "
        f"mode={'write' if args.write else 'check'} components={len(SOURCE_COMPONENTS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
