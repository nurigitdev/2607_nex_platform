#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.deployment_environments import (  # noqa: E402
    ARTIFACT_REFERENCE_ENVIRONMENTS,
    required_environment_names_for_composition,
)
from nex_runtime.deployment_lifecycle import (  # noqa: E402
    build_packaged_deployment_lifecycle_plan,
    packaged_deployment_lifecycle_projection,
)
from nex_runtime.topology import RUNTIME_PROFILES  # noqa: E402


SCHEMA_VERSION = "platform_packaged_lifecycle_evidence.v1"
_ENDPOINT_PORTS = {
    "NEX_OA_BASE_URL": 18101,
    "NEX_AG_BASE_URL": 18102,
    "NEX_AE_API_BASE_URL": 18103,
    "NEX_CX_BASE_URL": 18104,
    "NEX_MO_BASE_URL": 18105,
    "NEX_AE_WEB_BASE_URL": 15173,
}


def run_platform_packaged_lifecycle() -> dict[str, Any]:
    plans = [
        packaged_deployment_lifecycle_projection(
            build_packaged_deployment_lifecycle_plan(
                profile,
                environ=_synthetic_environment(profile),
            )
        )
        for profile in RUNTIME_PROFILES
    ]
    by_profile = {plan["profile"]: plan for plan in plans}
    serialized = json.dumps(plans, sort_keys=True)
    checks = {
        "five_profiles_planned": set(by_profile) == set(RUNTIME_PROFILES),
        "thirteen_processes_each": all(
            len(plan["process_steps"]) == 13 for plan in plans
        ),
        "migration_order_is_service_dependency_order": all(
            [step["service_id"] for step in plan["migration_steps"]]
            == ["nex-oa", "nex-mo", "nex-cx", "nex-ae-api", "nex-ag"]
            for plan in plans
            if plan["profile"] != "local_mock"
        ),
        "local_mock_skips_postgres_migrations": (
            by_profile["local_mock"]["migration_steps"] == []
        ),
        "stop_order_reverses_startup": all(
            plan["stop_order"]
            == list(
                reversed(
                    [
                        process_id
                        for layer in plan["start_layers"]
                        for process_id in layer
                    ]
                )
            )
            for plan in plans
        ),
        "protected_profiles_use_readiness": all(
            all(
                step["probe_mode"] in {"readiness", "process_alive_twice"}
                for step in by_profile[profile]["process_steps"]
            )
            for profile in ("test", "local_live", "staging_live", "production")
        ),
        "complete_set_rollback_only": all(
            len(plan["complete_artifact_set"]) == 6
            and plan["mixed_artifact_set_allowed"] is False
            and plan["database_downgrade_allowed"] is False
            for plan in plans
        ),
        "production_remains_blocked": (
            by_profile["production"]["status"] == "BLOCKED"
            and by_profile["production"]["production_contact_allowed"] is False
        ),
        "runtime_values_not_projected": (
            all(plan["runtime_values_included"] is False for plan in plans)
            and "synthetic-token" not in serialized
            and "postgresql://" not in serialized
            and "registry.example" not in serialized
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1418",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "plans": plans,
        "summary": {
            "profile_count": len(plans),
            "process_step_count": sum(len(plan["process_steps"]) for plan in plans),
            "migration_step_count": sum(
                len(plan["migration_steps"]) for plan in plans
            ),
            "artifact_set_size": len(plans[0]["complete_artifact_set"]),
            "blocked_profile_count": sum(
                plan["status"] == "BLOCKED" for plan in plans
            ),
        },
        "decision": {
            "database_contact_required": False,
            "provider_contact_required": False,
            "production_contact_required": False,
            "automatic_database_downgrade_allowed": False,
            "next_slice": "1419" if passed else "blocked",
        },
    }


def _synthetic_environment(profile: str) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in required_environment_names_for_composition(profile):
        if name.endswith("DATABASE_URL"):
            database = name.lower().removeprefix("nex_").removesuffix("_database_url")
            environment[name] = (
                f"postgresql://user:synthetic@db.internal/nex_{database}"
            )
        elif name in _ENDPOINT_PORTS:
            environment[name] = f"http://127.0.0.1:{_ENDPOINT_PORTS[name]}"
        elif name.endswith("_URL"):
            environment[name] = f"https://provider.internal/{name.lower()}"
        else:
            environment[name] = "synthetic-token"
    if profile in {"test", "staging_live", "production"}:
        for artifact_id, name in ARTIFACT_REFERENCE_ENVIRONMENTS.items():
            digest = hashlib.sha256(artifact_id.encode("ascii")).hexdigest()
            environment[name] = f"registry.example/nex/{artifact_id}@sha256:{digest}"
    return environment


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"platform_packaged_lifecycle=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_packaged_lifecycle=pass "
        f"profiles={summary.get('profile_count', 0)} "
        f"processes={summary.get('process_step_count', 0)} "
        f"migrations={summary.get('migration_step_count', 0)} "
        f"artifacts={summary.get('artifact_set_size', 0)} "
        f"blocked={summary.get('blocked_profile_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_packaged_lifecycle()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "issues": [str(exc)]}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
