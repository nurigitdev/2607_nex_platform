#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_secret_materialization import (  # noqa: E402
    materialize_production_secrets,
)
from nex_runtime.production_secret_rotation import (  # noqa: E402
    OWNER_ORDER,
    OwnerRotationObservation,
    build_secret_rotation_plan,
    evaluate_secret_rotation,
    secret_rotation_projection,
)
from run_platform_production_secret_materialization import (  # noqa: E402
    _DeterministicSecretResolver,
)
from run_platform_production_startup_admission import (  # noqa: E402
    _synthetic_environment,
)


SCHEMA_VERSION = "platform_production_secret_rotation_evidence.v1"


def run_platform_production_secret_rotation(root: Path = ROOT) -> dict[str, Any]:
    previous_env = _synthetic_environment(root)
    candidate_env = _candidate_environment(previous_env)
    previous = materialize_production_secrets(
        previous_env, _DeterministicSecretResolver(), root=root
    )
    candidate = materialize_production_secrets(
        candidate_env, _DeterministicSecretResolver(), root=root
    )
    plan = build_secret_rotation_plan(previous, candidate)
    observations = _observations(plan)
    prepared = evaluate_secret_rotation(plan, ())
    partial = evaluate_secret_rotation(plan, observations[:2])
    verified = evaluate_secret_rotation(plan, observations)
    failed_values = list(observations)
    failed_values[2] = OwnerRotationObservation(
        owner=failed_values[2].owner,
        generation=plan.candidate_generation,
        restart_completed=True,
        readiness_verified=False,
        secret_count=failed_values[2].secret_count,
    )
    failed = evaluate_secret_rotation(plan, failed_values)
    projection = secret_rotation_projection(plan, verified)
    passed = (
        prepared.status == "PREPARED"
        and partial.status == "ACTIVATING"
        and not partial.retire_previous_approved
        and verified.status == "VERIFIED"
        and verified.retire_previous_approved
        and failed.status == "ROLLBACK_REQUIRED"
        and failed.rollback_owners == tuple(reversed(OWNER_ORDER))
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1427",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "rotation": projection,
        "state_checks": {
            "prepared": prepared.status == "PREPARED",
            "partial_blocks_retirement": (
                partial.status == "ACTIVATING"
                and not partial.retire_previous_approved
            ),
            "all_owners_verified": verified.status == "VERIFIED",
            "failed_owner_requires_rollback": failed.status
            == "ROLLBACK_REQUIRED",
            "rollback_order_is_reverse": failed.rollback_owners
            == tuple(reversed(OWNER_ORDER)),
        },
        "summary": {
            "owner_count": len(OWNER_ORDER),
            "phase_count": len(plan.phases),
            "rollback_phase_count": len(plan.rollback_phases),
            "verified_owner_count": len(verified.verified_owners),
        },
        "decision": {
            "rotation_contract_verified": passed,
            "external_secret_provider_contacted": False,
            "previous_generation_retired": False,
            "production_deployment_approved": False,
            "next_slice": "1428" if passed else "blocked",
        },
    }


def _candidate_environment(previous: Mapping[str, str]) -> dict[str, str]:
    candidate = dict(previous)
    candidate["NEX_SECRET_GENERATION"] = "secret:2026-10-07.2"
    for name, value in tuple(candidate.items()):
        if name.endswith("_REF") and value.startswith("secret://"):
            candidate[name] = value.rsplit("@", 1)[0] + "@v2"
    return candidate


def _observations(plan) -> tuple[OwnerRotationObservation, ...]:
    counts = {
        item.owner: len(item.secrets) for item in plan.candidate.owner_environments
    }
    return tuple(
        OwnerRotationObservation(
            owner=owner,
            generation=plan.candidate_generation,
            restart_completed=True,
            readiness_verified=True,
            secret_count=counts[owner],
        )
        for owner in OWNER_ORDER
    )


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_secret_rotation=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_secret_rotation=pass "
        f"owners={summary.get('owner_count', 0)} "
        f"phases={summary.get('phase_count', 0)} "
        f"rollback={summary.get('rollback_phase_count', 0)} "
        f"verified={summary.get('verified_owner_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_secret_rotation()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
