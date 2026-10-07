#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_api_key_custody import (  # noqa: E402
    PROVIDER_API_KEY_ENV_NAMES,
    ProductionApiKeyCustodyError,
    admit_production_api_key_custody,
    production_api_key_custody_projection,
    redact_sensitive_runtime_data,
)
from nex_runtime.production_secret_materialization import (  # noqa: E402
    OwnerSecretEnvironment,
    materialize_production_secrets,
)
from run_platform_production_secret_materialization import (  # noqa: E402
    _DeterministicSecretResolver,
)
from run_platform_production_startup_admission import (  # noqa: E402
    _synthetic_environment,
)


SCHEMA_VERSION = "platform_production_api_key_custody_evidence.v1"


def run_platform_production_api_key_custody(root: Path = ROOT) -> dict[str, Any]:
    materialization = materialize_production_secrets(
        _synthetic_environment(root), _DeterministicSecretResolver(), root=root
    )
    custody = admit_production_api_key_custody(materialization)
    projection = production_api_key_custody_projection(custody)
    mo_values = materialization.environment_for("nex-mo")
    keys = tuple(mo_values[name] for name in PROVIDER_API_KEY_ENV_NAMES)
    unsafe = {
        "Authorization": f"Bearer {keys[0]}",
        "nested": {
            "provider_api_key": keys[1],
            "detail": f"provider rejected credential {keys[2]}",
        },
        "argv": ("--api-key", keys[0]),
    }
    redacted = redact_sensitive_runtime_data(unsafe, sensitive_values=keys)
    serialized = json.dumps(redacted, sort_keys=True)
    redaction_passed = all(value not in serialized for value in keys)

    leaked_owner = next(
        item for item in materialization.owner_environments if item.owner == "nex-oa"
    )
    mo_secret = next(
        secret
        for item in materialization.owner_environments
        if item.owner == "nex-mo"
        for secret in item.secrets
        if secret.target_environment_name == PROVIDER_API_KEY_ENV_NAMES[0]
    )
    contaminated = replace(
        materialization,
        owner_environments=tuple(
            replace(item, secrets=(*item.secrets, mo_secret))
            if item.owner == leaked_owner.owner
            else item
            for item in materialization.owner_environments
        ),
    )
    try:
        admit_production_api_key_custody(contaminated)
    except ProductionApiKeyCustodyError:
        cross_owner_blocked = True
    else:
        cross_owner_blocked = False
    passed = redaction_passed and cross_owner_blocked
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1428",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "custody": projection,
        "checks": {
            "mo_only_custody": projection["owner"] == "nex-mo",
            "three_provider_keys_configured": projection["configured_key_count"] == 3,
            "cross_owner_exposure_blocked": cross_owner_blocked,
            "nested_runtime_data_redacted": redaction_passed,
        },
        "summary": {
            "provider_api_key_count": projection["configured_key_count"],
            "non_owner_exposure_count": projection["non_owner_exposure_count"],
            "redaction_leak_count": sum(value in serialized for value in keys),
        },
        "decision": {
            "api_key_custody_verified": passed,
            "external_provider_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1429" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_api_key_custody=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_api_key_custody=pass "
        f"keys={summary.get('provider_api_key_count', 0)} "
        f"exposures={summary.get('non_owner_exposure_count', 0)} "
        f"leaks={summary.get('redaction_leak_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_api_key_custody()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
