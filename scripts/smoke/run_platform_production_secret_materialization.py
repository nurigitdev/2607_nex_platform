#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_secret_materialization import (  # noqa: E402
    ProductionSecretMaterializationError,
    ResolvedSecret,
    SecretResolutionContext,
    materialize_production_secrets,
    production_secret_materialization_projection,
)
from run_platform_production_startup_admission import (  # noqa: E402
    _synthetic_environment,
)


SCHEMA_VERSION = "platform_production_secret_materialization_evidence.v1"


class _DeterministicSecretResolver:
    def __init__(self, mutation: str | None = None) -> None:
        self.mutation = mutation

    def resolve(
        self,
        reference: str,
        *,
        context: SecretResolutionContext,
    ) -> ResolvedSecret:
        if self.mutation == "exception":
            raise RuntimeError("provider detail must be sanitized")
        secret = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id=urlsplit(reference).hostname or "",
            value=f"material-{context.target_environment_name.lower()}",
        )
        if self.mutation == "wrong_owner":
            return replace(secret, owner="nex-wrong")
        if self.mutation == "empty_value":
            return replace(secret, value="")
        return secret


def run_platform_production_secret_materialization(
    root: Path = ROOT,
) -> dict[str, Any]:
    environment = _synthetic_environment(root)
    materialization = materialize_production_secrets(
        environment,
        _DeterministicSecretResolver(),
        root=root,
    )
    projection = production_secret_materialization_projection(materialization)
    owner_counts = {
        item["owner"]: item["secret_count"] for item in projection["owners"]
    }
    fail_closed_cases = {}
    for case_id, resolver in (
        ("resolver_failure", _DeterministicSecretResolver("exception")),
        ("wrong_owner", _DeterministicSecretResolver("wrong_owner")),
        ("empty_value", _DeterministicSecretResolver("empty_value")),
    ):
        try:
            materialize_production_secrets(environment, resolver, root=root)
        except ProductionSecretMaterializationError:
            fail_closed_cases[case_id] = True
        else:
            fail_closed_cases[case_id] = False
    serialized = json.dumps(projection, sort_keys=True)
    leaked = any(
        value in serialized
        for owner in materialization.owner_environments
        for value in owner.process_environment().values()
    )
    passed = (
        owner_counts
        == {
            "nex-oa": 2,
            "nex-ag": 5,
            "nex-ae-api": 3,
            "nex-cx": 2,
            "nex-mo": 4,
        }
        and all(fail_closed_cases.values())
        and not leaked
    )
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1426",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "materialization": projection,
        "owner_secret_counts": owner_counts,
        "fail_closed_cases": fail_closed_cases,
        "summary": {
            "owner_count": projection["owner_count"],
            "secret_count": projection["secret_count"],
            "fail_closed_case_count": len(fail_closed_cases),
            "secret_value_leak_count": int(leaked),
        },
        "decision": {
            "owner_scoped_materialization_enforced": passed,
            "external_secret_provider_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1427" if passed else "blocked",
        },
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return "platform_production_secret_materialization=fail"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_production_secret_materialization=pass "
        f"owners={summary.get('owner_count', 0)} "
        f"secrets={summary.get('secret_count', 0)} "
        f"fail_closed={summary.get('fail_closed_case_count', 0)} "
        f"leaks={summary.get('secret_value_leak_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_platform_production_secret_materialization()
    except (OSError, ValueError) as exc:
        result = {"status": "FAIL", "detail": str(exc)}
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
