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
    environment_composition_manifest_projection,
    environment_composition_projection,
    load_environment_compositions,
    required_environment_names_for_composition,
    resolve_environment_composition,
)
from nex_runtime.topology import RUNTIME_PROFILES  # noqa: E402


SCHEMA_VERSION = "platform_environment_compositions_evidence.v1"


def run_platform_environment_compositions(root: Path = ROOT) -> dict[str, Any]:
    definitions = load_environment_compositions(root)
    manifests = [
        environment_composition_manifest_projection(definition)
        for definition in definitions
    ]
    resolutions = []
    for profile in RUNTIME_PROFILES:
        environment = _synthetic_environment(profile)
        resolution = resolve_environment_composition(
            profile,
            environ=environment,
            definitions=definitions,
        )
        resolutions.append(environment_composition_projection(resolution))
    by_profile = {item["profile"]: item for item in resolutions}
    serialized = json.dumps(
        {"manifests": manifests, "resolutions": resolutions},
        sort_keys=True,
    )
    checks = {
        "four_environment_classes": len(manifests) == 4,
        "five_profiles_covered_once": (
            len(resolutions) == 5
            and {item["profile"] for item in resolutions} == set(RUNTIME_PROFILES)
        ),
        "development_local_mock_is_limited": (
            by_profile["local_mock"]["environment_class"] == "development"
            and by_profile["local_mock"]["status"] == "LIMITED"
        ),
        "test_requires_six_immutable_artifacts": (
            by_profile["test"]["environment_class"] == "test"
            and by_profile["test"]["artifact_reference_count"] == 6
            and len(by_profile["test"]["required_artifact_environment_names"])
            == 6
        ),
        "live_background_profiles_fail_closed": all(
            by_profile[profile]["status"] == "BLOCKED"
            and "background_execution_profile_not_admitted"
            in by_profile[profile]["reason_codes"]
            for profile in ("local_live", "staging_live", "production")
        ),
        "production_approval_remains_deferred": (
            "production_deployment_approval_deferred"
            in by_profile["production"]["reason_codes"]
        ),
        "artifact_values_are_not_projected": all(
            item["artifact_reference_values_included"] is False
            for item in resolutions
        ),
        "no_synthetic_values_leaked": (
            "synthetic-token" not in serialized
            and "postgresql://" not in serialized
            and "registry.example" not in serialized
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1417",
        "requirement": "S142",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "manifests": manifests,
        "resolutions": resolutions,
        "summary": {
            "environment_class_count": len(manifests),
            "profile_count": len(resolutions),
            "limited_profile_count": sum(
                item["status"] == "LIMITED" for item in resolutions
            ),
            "blocked_profile_count": sum(
                item["status"] == "BLOCKED" for item in resolutions
            ),
            "immutable_profile_count": sum(
                item["artifact_reference_count"] == 6 for item in resolutions
            ),
        },
        "decision": {
            "orchestrator_selected": False,
            "secret_values_stored": False,
            "production_contact_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1418" if passed else "blocked",
        },
    }


def _synthetic_environment(profile: str) -> dict[str, str]:
    environment = {}
    for name in required_environment_names_for_composition(profile):
        if name.endswith("DATABASE_URL"):
            environment[name] = "postgresql://user:synthetic@db.internal/database"
        elif name.endswith("BASE_URL") or name.endswith("_URL"):
            environment[name] = "https://runtime.internal"
        else:
            environment[name] = "synthetic-token"
    if profile in {"test", "staging_live", "production"}:
        for artifact_id, name in ARTIFACT_REFERENCE_ENVIRONMENTS.items():
            digest = hashlib.sha256(artifact_id.encode("ascii")).hexdigest()
            environment[name] = f"registry.example/nex/{artifact_id}@sha256:{digest}"
    return environment


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_environment_compositions=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_environment_compositions=pass "
        f"classes={summary.get('environment_class_count', 0)} "
        f"profiles={summary.get('profile_count', 0)} "
        f"limited={summary.get('limited_profile_count', 0)} "
        f"blocked={summary.get('blocked_profile_count', 0)} "
        f"immutable={summary.get('immutable_profile_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_environment_compositions()
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
