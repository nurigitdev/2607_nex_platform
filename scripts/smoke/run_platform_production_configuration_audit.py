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

from nex_runtime.runtime_profiles import (  # noqa: E402
    DATABASE_ENV_NAMES,
    LIVE_PROVIDER_ENV_NAMES,
    PROFILE_MODES,
    SERVICE_ENDPOINT_ENV_NAMES,
    SIGNED_TRUST_ENV_NAMES,
    RuntimeProfileError,
    resolve_runtime_profile,
    runtime_profile_environment_overlay,
)


SCHEMA_VERSION = "platform_production_configuration_audit.v1"
PLAN_PATH = "docs/48_platform_production_readiness_plan.md"


@dataclass(frozen=True)
class ConfigGap:
    gap_id: str
    owners: tuple[str, ...]
    targets: tuple[str, ...]
    evidence_path: str
    evidence_token: str


CONFIG_GAPS = (
    ConfigGap(
        "immutable_deployment_environment",
        ("platform_integration",),
        ("S142",),
        "services/_shared/nex_runtime/topology.py",
        "class PlatformRuntimeManifest:",
    ),
    ConfigGap(
        "external_secret_provider_rotation",
        ("platform_integration", "OA", "AE", "CX", "MO", "AG"),
        ("S143",),
        "services/_shared/nex_runtime/runtime_profiles.py",
        "PLACEHOLDER_MARKERS",
    ),
    ConfigGap(
        "managed_tls_certificate_lifecycle",
        ("platform_integration",),
        ("S143",),
        "services/_shared/nex_runtime/topology.py",
        'parsed.scheme in {"http", "https"}',
    ),
    ConfigGap(
        "external_signing_key_custody",
        ("OA",),
        ("S144",),
        "services/nex-oa/README.md",
        "fail-closed until a KMS, Vault, or PKCS#11 signing provider is injected",
    ),
    ConfigGap(
        "enterprise_idp_registration",
        ("OA",),
        ("S144",),
        "services/nex-oa/nex_oa/oidc_verifier.py",
        "OIDC_ID_TOKEN_ALGORITHM",
    ),
    ConfigGap(
        "postgresql_backup_ha_dr",
        ("OA", "AE", "CX", "MO", "AG", "platform_integration"),
        ("S145",),
        "services/_shared/nex_runtime/release_candidate_assurance.py",
        "production_postgresql_backup_ha_dr",
    ),
    ConfigGap(
        "object_storage_lifecycle",
        ("CX", "AE"),
        ("S146",),
        "services/nex-cx/nex_cx/private_text_store.py",
        "/data/nex-platform/cx/private-text",
    ),
    ConfigGap(
        "external_incident_delivery",
        ("AG",),
        ("S148",),
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        'DISPATCH_EXTERNAL_INCIDENT_BASE_URL_ENV = "NEX_AG_EXTERNAL_INCIDENT_BASE_URL"',
    ),
    ConfigGap(
        "gpu_scheduling_capacity",
        ("MO",),
        ("S147",),
        "services/_shared/nex_runtime/release_candidate_assurance.py",
        "production_gpu_scheduling_capacity",
    ),
    ConfigGap(
        "monitoring_paging_slo_approval",
        ("AG", "platform_integration"),
        ("S148", "S150"),
        "services/_shared/nex_runtime/release_candidate_assurance.py",
        "production_monitoring_paging_slo_approval",
    ),
)


def run_platform_production_configuration_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    profile = _production_profile_evidence()
    plan = _read_text(root / PLAN_PATH)
    gap_checks = {
        item.gap_id: {
            "source_evidence_present": item.evidence_token
            in _read_text(root / item.evidence_path),
            "canonical_gap_documented": f"`{item.gap_id}`" in plan,
            "owners_present": bool(item.owners),
            "targets_present": bool(item.targets),
        }
        for item in CONFIG_GAPS
    }
    checks = {
        "production_mode_exact": profile["modes"]
        == {
            "persistence": "postgres",
            "provider": "live",
            "trust": "signed",
            "ag_projection": "api",
        },
        "required_environment_inventory_exact": profile["required_count"] == 25,
        "missing_environment_fails_closed": profile["missing_error_count"] == 25,
        "placeholder_fails_closed": profile["placeholder_rejected"] is True,
        "mode_conflict_fails_closed": profile["mode_conflict_rejected"] is True,
        "secure_cookie_selected": profile["secure_cookie"] == "true",
        "ten_config_gaps_frozen": len(CONFIG_GAPS) == 10,
        "all_gap_evidence_present": all(
            values["source_evidence_present"] for values in gap_checks.values()
        ),
        "all_gaps_documented_owned_targeted": all(
            values["canonical_gap_documented"]
            and values["owners_present"]
            and values["targets_present"]
            for values in gap_checks.values()
        ),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = all(checks.values())
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1405",
        "requirement": "S141",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": issues,
        "production_profile": profile,
        "config_gaps": [
            {
                "gap_id": item.gap_id,
                "owners": list(item.owners),
                "targets": list(item.targets),
                "state": "NOT_ADMITTED",
                "checks": gap_checks[item.gap_id],
            }
            for item in CONFIG_GAPS
        ],
        "summary": {
            "required_environment_count": profile["required_count"],
            "database_environment_count": len(DATABASE_ENV_NAMES),
            "service_endpoint_count": len(SERVICE_ENDPOINT_ENV_NAMES),
            "signed_trust_environment_count": len(SIGNED_TRUST_ENV_NAMES),
            "live_provider_environment_count": len(LIVE_PROVIDER_ENV_NAMES),
            "config_gap_count": len(CONFIG_GAPS),
        },
        "decision": {
            "environment_values_are_control_evidence": False,
            "production_admission_complete": False,
            "production_connection_required": False,
            "next_slice": "1406" if passed else "blocked",
        },
    }


def _production_profile_evidence() -> dict[str, Any]:
    required_names = (
        *DATABASE_ENV_NAMES,
        *SERVICE_ENDPOINT_ENV_NAMES,
        *SIGNED_TRUST_ENV_NAMES,
        *LIVE_PROVIDER_ENV_NAMES,
    )
    environment = {name: "configured-value" for name in required_names}
    environment.update(runtime_profile_environment_overlay("production"))
    resolution = resolve_runtime_profile("production", environ=environment)

    try:
        resolve_runtime_profile("production", environ={})
        missing_error_count = 0
    except RuntimeProfileError as exc:
        missing_error_count = len(exc.errors)

    placeholder_environment = dict(environment)
    placeholder_environment[required_names[0]] = "<secret>"
    placeholder_rejected = _profile_rejected(placeholder_environment)

    conflict_environment = dict(environment)
    conflict_environment["NEX_PERSISTENCE_MODE"] = "memory"
    mode_conflict_rejected = _profile_rejected(conflict_environment)
    return {
        "profile": resolution.profile,
        "protected": resolution.protected,
        "modes": {
            "persistence": resolution.modes.persistence,
            "provider": resolution.modes.provider,
            "trust": resolution.modes.trust,
            "ag_projection": resolution.modes.ag_projection,
        },
        "required_count": len(resolution.required_environment_names),
        "missing_error_count": missing_error_count,
        "placeholder_rejected": placeholder_rejected,
        "mode_conflict_rejected": mode_conflict_rejected,
        "secure_cookie": environment["NEX_AE_SESSION_COOKIE_SECURE"],
    }


def _profile_rejected(environment: Mapping[str, str]) -> bool:
    try:
        resolve_runtime_profile("production", environ=environment)
    except RuntimeProfileError:
        return True
    return False


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_production_configuration_audit=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_configuration_audit=pass "
        f"required={summary.get('required_environment_count', 0)} "
        f"db={summary.get('database_environment_count', 0)} "
        f"endpoints={summary.get('service_endpoint_count', 0)} "
        f"trust={summary.get('signed_trust_environment_count', 0)} "
        f"providers={summary.get('live_provider_environment_count', 0)} "
        f"gaps={summary.get('config_gap_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_configuration_audit()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
