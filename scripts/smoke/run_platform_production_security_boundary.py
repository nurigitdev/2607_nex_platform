#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_environments import (  # noqa: E402
    load_environment_compositions,
)
from nex_runtime.runtime_profiles import (  # noqa: E402
    DATABASE_ENV_NAMES,
    LIVE_PROVIDER_ENV_NAMES,
    SERVICE_ENDPOINT_ENV_NAMES,
    SIGNED_TRUST_ENV_NAMES,
    resolve_runtime_profile,
    runtime_profile_environment_overlay,
)


SCHEMA_VERSION = "platform_production_security_boundary.v1"
CANONICAL_PATH = "docs/51_platform_production_configuration_secret_tls.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
RUNNER_NAME = "run_platform_production_security_boundary.py"


@dataclass(frozen=True)
class ProductionSecurityGap:
    gap_id: str
    owner: str
    target_slices: tuple[str, ...]


SECRET_ENV_NAMES = (
    *DATABASE_ENV_NAMES,
    *SIGNED_TRUST_ENV_NAMES,
    *(name for name in LIVE_PROVIDER_ENV_NAMES if name.endswith("_API_KEY")),
)
PUBLIC_CONNECTION_ENV_NAMES = (
    *SERVICE_ENDPOINT_ENV_NAMES,
    *(name for name in LIVE_PROVIDER_ENV_NAMES if not name.endswith("_API_KEY")),
)
TLS_ENDPOINT_ENV_NAMES = PUBLIC_CONNECTION_ENV_NAMES
PRODUCTION_SECURITY_GAPS = (
    ProductionSecurityGap(
        "typed_production_config_manifest", "platform_integration", ("1424",)
    ),
    ProductionSecurityGap(
        "secret_classification_and_reference",
        "platform_integration_and_service_owners",
        ("1424",),
    ),
    ProductionSecurityGap(
        "fail_closed_startup_admission", "platform_integration", ("1425",)
    ),
    ProductionSecurityGap(
        "external_secret_injection",
        "platform_integration_and_service_owners",
        ("1426",),
    ),
    ProductionSecurityGap(
        "secret_rotation_reload_rollback",
        "platform_integration_and_service_owners",
        ("1427",),
    ),
    ProductionSecurityGap(
        "api_key_custody_redaction", "MO_and_platform_integration", ("1428",)
    ),
    ProductionSecurityGap(
        "managed_tls_termination", "platform_integration", ("1429",)
    ),
    ProductionSecurityGap(
        "certificate_renewal_expiry_rollback",
        "platform_integration",
        ("1429",),
    ),
    ProductionSecurityGap(
        "protected_staging_acceptance", "platform_integration", ("1430", "1431")
    ),
)
REQUIRED_PATHS = (
    "docs/48_platform_production_readiness_plan.md",
    "docs/49_platform_production_readiness_reaudit.md",
    "docs/50_platform_reproducible_deployment_packaging.md",
    CANONICAL_PATH,
    "docs/slices/1423_platform_production_security_boundary.md",
    "deployment/environments/production.yaml",
    "services/_shared/nex_runtime/runtime_profiles.py",
    "services/_shared/nex_runtime/deployment_environments.py",
    QUALITY_GATE_PATH,
)


def run_platform_production_security_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    production = next(
        (
            item
            for item in load_environment_compositions(root)
            if item.environment_class == "production"
        ),
        None,
    ) if all(paths.values()) else None
    required_names = (
        *DATABASE_ENV_NAMES,
        *SERVICE_ENDPOINT_ENV_NAMES,
        *SIGNED_TRUST_ENV_NAMES,
        *LIVE_PROVIDER_ENV_NAMES,
    )
    environment = {name: "configured-value" for name in required_names}
    environment.update(runtime_profile_environment_overlay("production"))
    resolution = resolve_runtime_profile("production", environ=environment)
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    checks = {
        "required_paths_present": all(paths.values()),
        "production_profile_requires_twenty_five_values": (
            len(resolution.required_environment_names) == 25
            and set(resolution.required_environment_names) == set(required_names)
        ),
        "secret_inventory_exact": (
            len(SECRET_ENV_NAMES) == 16
            and len(set(SECRET_ENV_NAMES)) == 16
        ),
        "public_connection_inventory_exact": (
            len(PUBLIC_CONNECTION_ENV_NAMES) == 9
            and len(set(PUBLIC_CONNECTION_ENV_NAMES)) == 9
        ),
        "required_values_classified_once": (
            set(SECRET_ENV_NAMES).isdisjoint(PUBLIC_CONNECTION_ENV_NAMES)
            and set((*SECRET_ENV_NAMES, *PUBLIC_CONNECTION_ENV_NAMES))
            == set(required_names)
        ),
        "nine_tls_endpoints_frozen": (
            len(TLS_ENDPOINT_ENV_NAMES) == 9
            and set(TLS_ENDPOINT_ENV_NAMES) == set(PUBLIC_CONNECTION_ENV_NAMES)
        ),
        "external_reference_composition_is_fail_closed": (
            production is not None
            and production.secret_source == "external_reference"
            and production.immutable_artifacts_required
            and not production.allow_loopback
            and not production.allow_local_storage
            and not production.production_contact_allowed
        ),
        "nine_security_gaps_documented": (
            len(PRODUCTION_SECURITY_GAPS) == 9
            and all(f"`{item.gap_id}`" in canonical for item in PRODUCTION_SECURITY_GAPS)
        ),
        "slice_sequence_and_gates_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1423, 1433))
            and "Checkpoint Gate at Slice 1427" in canonical
            and "Full Gate at Slice 1432" in canonical
        ),
        "external_acceptance_remains_required": (
            "actual external staging acceptance remains mandatory" in canonical.lower()
            and "production deployment remains unapproved" in canonical.lower()
        ),
        "quality_hook_registered_once": quality_gate.count(RUNNER_NAME) == 1,
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items()
        if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1423",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "secret_environment_names": list(SECRET_ENV_NAMES),
        "public_connection_environment_names": list(PUBLIC_CONNECTION_ENV_NAMES),
        "tls_endpoint_environment_names": list(TLS_ENDPOINT_ENV_NAMES),
        "gaps": [
            {
                "gap_id": item.gap_id,
                "owner": item.owner,
                "target_slices": list(item.target_slices),
                "state": "OPEN",
            }
            for item in PRODUCTION_SECURITY_GAPS
        ],
        "summary": {
            "required_path_count": sum(paths.values()),
            "required_environment_count": len(required_names),
            "secret_environment_count": len(SECRET_ENV_NAMES),
            "public_connection_count": len(PUBLIC_CONNECTION_ENV_NAMES),
            "tls_endpoint_count": len(TLS_ENDPOINT_ENV_NAMES),
            "gap_count": len(PRODUCTION_SECURITY_GAPS),
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "provider_neutral_contract_required": True,
            "external_secret_provider_required_for_closure": True,
            "managed_tls_endpoint_required_for_closure": True,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1424" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_production_security_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_security_boundary=pass "
        f"required={summary.get('required_environment_count', 0)} "
        f"secrets={summary.get('secret_environment_count', 0)} "
        f"connections={summary.get('public_connection_count', 0)} "
        f"tls={summary.get('tls_endpoint_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_security_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

