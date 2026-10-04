#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.runtime_profiles import (  # noqa: E402
    DATABASE_ENV_NAMES,
    LIVE_PROVIDER_ENV_NAMES,
    SIGNED_TRUST_ENV_NAMES,
    TEST_DATABASE_ENV_NAMES,
    RuntimeProfileError,
    resolve_runtime_profile,
    runtime_profile_environment_overlay,
    runtime_profile_public_projection,
)
from nex_runtime.topology import RUNTIME_PROFILES  # noqa: E402


def run_platform_runtime_profile_composition() -> dict[str, Any]:
    projections = []
    for profile in RUNTIME_PROFILES:
        environment = runtime_profile_environment_overlay(profile)
        required_names = ()
        if profile != "local_mock":
            database_names = (
                TEST_DATABASE_ENV_NAMES if profile == "test" else DATABASE_ENV_NAMES
            )
            provider_names = () if profile == "test" else LIVE_PROVIDER_ENV_NAMES
            required_names = (*database_names, *SIGNED_TRUST_ENV_NAMES, *provider_names)
        for name in required_names:
            environment[name] = _synthetic_value(name)
        projections.append(
            runtime_profile_public_projection(
                resolve_runtime_profile(profile, environ=environment)
            )
        )

    try:
        resolve_runtime_profile("production", environ={})
    except RuntimeProfileError as exc:
        protected_failure_count = len(exc.errors)
        protected_failure_safe = all(
            "secret-value" not in error for error in exc.errors
        )
    else:  # pragma: no cover - guarded by focused tests.
        protected_failure_count = 0
        protected_failure_safe = False

    by_profile = {item["profile"]: item for item in projections}
    checks = {
        "all_profiles_resolve": len(projections) == 5,
        "local_mock_has_no_requirements": by_profile["local_mock"][
            "required_environment_count"
        ]
        == 0,
        "test_is_mock_postgres_signed_api": by_profile["test"]["modes"]
        == {
            "persistence": "postgres",
            "provider": "mock",
            "trust": "signed",
            "ag_projection": "api",
        },
        "live_profiles_use_mo_live_mode": all(
            by_profile[name]["modes"]["provider"] == "live"
            for name in ("local_live", "staging_live", "production")
        ),
        "protected_missing_configuration_fails": protected_failure_count > 0,
        "failure_evidence_excludes_values": protected_failure_safe,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_runtime_profile_composition.v1",
        "slice": "1314",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_runtime_profile_composition_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "profiles": projections,
        "protected_failure_count": protected_failure_count,
        "decision": {
            "local_mock_remains_default": True,
            "protected_profiles_fail_closed": True,
            "environment_values_projected": False,
            "next_slice": "1315",
        },
    }


def _synthetic_value(name: str) -> str:
    if name.endswith("DATABASE_URL"):
        return "postgresql://user:secret-value@127.0.0.1:5432/database"
    if name.endswith("BASE_URL") or name.endswith("_URL"):
        return "https://runtime.internal"
    return "synthetic-secret-value"


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_runtime_profile_composition=fail issues={len(evidence.get('issues') or [])}"
    return (
        "platform_runtime_profile_composition=pass "
        f"profiles={len(evidence.get('profiles') or [])}/5 "
        f"protected_failures={evidence.get('protected_failure_count')} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_runtime_profile_composition()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
