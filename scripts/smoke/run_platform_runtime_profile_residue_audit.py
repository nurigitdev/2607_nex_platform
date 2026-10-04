#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_runtime_profile_residue_audit.v1"
EXPECTED_PROFILES = (
    "local_mock",
    "local_live",
    "test",
    "staging_live",
    "production",
)
BACKEND_SERVICES = ("nex-oa", "nex-ag", "nex-ae-api", "nex-cx", "nex-mo")
NON_MO_SERVICE_ROOTS = (
    "services/nex-oa",
    "services/nex-ae-api",
    "services/nex-cx",
    "services/nex-ag",
)
REMOTE_PROVIDER_ENV = re.compile(
    r"NEX_MO_(?:REMOTE_(?:EMBEDDING|RERANKER)_URL|"
    r"VLLM_(?:BASE_URL|CHAT_COMPLETIONS_URL|MODELS_URL))"
)


def run_platform_runtime_profile_residue_audit(
    root: Path = ROOT,
) -> dict[str, Any]:
    env_example = _read_text(root / ".env.example")
    environment_freeze = _read_text(
        root / "docs/32_platform_development_environment_freeze.md"
    )
    web_runtime = _read_text(root / "apps/nex-ae-web/src/runtimeConfig.js")
    service_runner = _read_text(root / "scripts/dev/run_all_services.py")
    service_shell = _read_text(root / "scripts/dev/run_service.py")
    direct_provider_references = _direct_provider_references(root)

    declared_profiles = [
        profile
        for profile in EXPECTED_PROFILES
        if f"`{profile}`" in environment_freeze
    ]
    runner_services = [
        service_id for service_id in BACKEND_SERVICES if f'"{service_id}"' in service_runner
    ]
    checks = {
        "five_runtime_profiles_documented": declared_profiles
        == list(EXPECTED_PROFILES),
        "local_mock_is_repository_default": "NEX_PROFILE=local_mock" in env_example,
        "provider_mode_defaults_to_mock": "NEX_MO_PROVIDER_MODE=mock" in env_example,
        "persistence_defaults_to_memory": "NEX_PERSISTENCE_MODE=memory" in env_example,
        "ag_projection_defaults_to_memory": (
            "NEX_AG_OPERATIONS_SOURCE_MODE=memory" in env_example
        ),
        "ae_web_defaults_to_mock": 'clientMode = config.client_mode || config.clientMode || "mock"'
        in web_runtime,
        "ae_web_fetch_requires_opt_in": "fetch_clients_enabled: false" in web_runtime,
        "backend_runner_starts_five_services": runner_services
        == list(BACKEND_SERVICES),
        "remote_provider_endpoints_are_mo_owned": not direct_provider_references,
    }
    issues = [name for name, passed in checks.items() if not passed]
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1304",
        "requirement": "S131",
        "status": "PASS" if not issues else "FAIL",
        "failure_code": (
            None if not issues else "platform_runtime_profile_residue_audit_failed"
        ),
        "checks": checks,
        "issues": issues,
        "declared_profiles": declared_profiles,
        "runner_services": runner_services,
        "direct_provider_references_outside_mo": direct_provider_references,
        "findings": {
            "mock_first_defaults": 4,
            "runtime_profile_count": len(declared_profiles),
            "backend_runner_service_count": len(runner_services),
            "backend_runner_includes_ae_web": "nex-ae-web" in service_runner,
            "backend_runner_waits_for_readiness": any(
                token in service_runner for token in ("/ready", "readiness")
            ),
            "service_shell_validates_runtime_profile": (
                "NEX_PROFILE" in service_shell and "EXPECTED_PROFILES" in service_shell
            ),
            "direct_provider_reference_count_outside_mo": len(
                direct_provider_references
            ),
            "canonical_runtime_profile_manifest_present": False,
        },
        "refactoring_candidates": [
            {
                "priority": "P0",
                "owner": "platform_integration",
                "gap": "materialize and validate each documented profile as one typed runtime manifest",
                "target_requirement": "S132",
            },
            {
                "priority": "P0",
                "owner": "platform_integration",
                "gap": "make multi-service startup dependency-aware and readiness-gated",
                "target_requirement": "S132",
            },
            {
                "priority": "P1",
                "owner": "nex-ae-web",
                "gap": "include AE Web in the explicit local topology without weakening mock-first defaults",
                "target_requirement": "S132",
            },
        ],
        "decision": {
            "mock_first_regression_retained": True,
            "live_provider_mode_remains_opt_in": True,
            "non_mo_provider_host_access_allowed": False,
            "current_runner_is_release_topology": False,
            "mutation_performed": False,
            "next_slice": "1305",
        },
    }


def _direct_provider_references(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative_root in NON_MO_SERVICE_ROOTS:
        service_root = root / relative_root
        if not service_root.is_dir():
            continue
        for path in service_root.rglob("*.py"):
            for env_name in sorted(set(REMOTE_PROVIDER_ENV.findall(_read_text(path)))):
                findings.append(
                    {
                        "service": relative_root.removeprefix("services/"),
                        "environment": env_name,
                        "path": str(path.relative_to(root)),
                    }
                )
    return findings


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_profile_residue=fail issues={len(evidence.get('issues') or [])}"
    findings = evidence.get("findings") or {}
    return (
        "platform_runtime_profile_residue=pass "
        f"profiles={findings.get('runtime_profile_count', 0)} "
        f"backends={findings.get('backend_runner_service_count', 0)} "
        f"web={findings.get('backend_runner_includes_ae_web')} "
        f"readiness={findings.get('backend_runner_waits_for_readiness')} "
        f"direct_provider_refs={findings.get('direct_provider_reference_count_outside_mo', 0)} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_runtime_profile_residue_audit()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
