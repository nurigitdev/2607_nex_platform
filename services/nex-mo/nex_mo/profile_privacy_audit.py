from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nex_mo.providers import build_model_profile_catalog


ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_PUBLIC_FIELDS = frozenset(
    {"model_path", "live_health_env", "provider_url", "provider_endpoint", "api_key"}
)


def build_mo_profile_privacy_refactor_checkpoint(
    root: Path = ROOT,
) -> dict[str, Any]:
    internal_root = "/private/mo-model-root"
    profiles = build_model_profile_catalog(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_MODEL_ROOT": internal_root,
        }
    )
    public_profiles = [profile.to_wire() for profile in profiles]
    serialized = json.dumps(public_profiles, sort_keys=True)
    schema_path = root / "contracts/schemas/service/nex_mo/model_profile.v1.schema.json"
    schema = _read_json(schema_path)
    negative_index = _read_json(root / "contracts/tests/negative/index.json")
    provider_source = _read_text(root / "services/nex-mo/nex_mo/providers.py")
    contract_source = _read_text(root / "docs/17_cx_mo_generation_provider_contract.md")
    schema_properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    negative_entries = (
        negative_index.get("negative_examples", [])
        if isinstance(negative_index, dict)
        else []
    )
    checks = {
        "internal_model_paths_retained": bool(profiles)
        and all(profile.model_path.startswith(internal_root) for profile in profiles),
        "public_profiles_exclude_private_fields": all(
            not (FORBIDDEN_PUBLIC_FIELDS & set(profile)) for profile in public_profiles
        ),
        "public_profiles_exclude_internal_root": internal_root not in serialized,
        "embedding_model_identity_canonical": public_profiles[0].get("model_name")
        == "Qwen3-Embedding-4B",
        "endpoint_metadata_excludes_model_root": '"model_root":' not in provider_source,
        "schema_is_closed_and_private_fields_absent": (
            schema.get("additionalProperties") is False
            and not (FORBIDDEN_PUBLIC_FIELDS & set(schema_properties))
        ),
        "model_path_negative_fixture_registered": any(
            item.get("name") == "mo_model_profile_model_path_leak"
            for item in negative_entries
            if isinstance(item, dict)
        ),
        "route_privacy_contract_present": (
            "it never exposes provider URL or model file path" in contract_source
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "checkpoint_schema_version": "mo_profile_privacy_refactor_checkpoint.v1",
        "slice": "1106",
        "requirement": "S111",
        "status": status,
        "failure_code": None if status == "PASS" else "mo_profile_privacy_refactor_failed",
        "refactor_readiness": "PRIVACY_BOUNDARY_REPAIRED" if status == "PASS" else "BLOCKED",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "internal_profile_count": len(profiles),
            "public_profile_count": len(public_profiles),
            "forbidden_public_field_count": sum(
                len(FORBIDDEN_PUBLIC_FIELDS & set(profile))
                for profile in public_profiles
            ),
            "remaining_catalog_drift_count": 4,
        },
        "public_profile_fields": sorted(
            set().union(*(set(profile) for profile in public_profiles))
            if public_profiles
            else set()
        ),
        "decision": {
            "internal_model_paths_retained_for_runtime": True,
            "public_model_paths_allowed": False,
            "public_health_environment_names_allowed": False,
            "canonical_embedding_model": "Qwen3-Embedding-4B",
            "new_table_required": False,
        },
        "next_slice": "1107",
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
