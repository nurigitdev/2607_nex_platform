#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.generation_policy import build_generation_policy_package  # noqa: E402
from nex_ae_api.prompts import DEFAULT_AE_PROMPT_STORE  # noqa: E402
from nex_ae_api.runtime_policy import resolve_runtime_policy  # noqa: E402
from nex_ae_api.runtime_policy_api import resolve_safe_prompt_binding  # noqa: E402


def run_ae_generation_policy_package() -> dict[str, Any]:
    source = {
        "user_message": "private grounded question",
        "tenant_id": "tenant-smoke",
        "owner_user_id": "user-smoke",
        "retrieval": {"enabled": True},
    }
    runtime_policy = resolve_runtime_policy(source)
    binding = resolve_safe_prompt_binding(
        DEFAULT_AE_PROMPT_STORE,
        binding_key=runtime_policy["prompt_contract_ref"]["prompt_binding_key"],
        prompt_version=runtime_policy["prompt_contract_ref"]["prompt_version"],
    )
    package = build_generation_policy_package(
        source,
        runtime_policy=runtime_policy,
        prompt_binding=binding,
        retrieval_package={
            "retrieval_package_id": "retrieval-smoke",
            "package_hash": "b" * 64,
            "status": "READY",
            "evidence_items": [
                {"evidence_id": "evidence-smoke", "text": "private evidence"}
            ],
        },
    )
    serialized = json.dumps(package, sort_keys=True)
    checks = {
        "canonical_schema": package["generation_policy_package_schema_version"]
        == "ae_generation_policy_package.v1",
        "grounded_mode": package["execution_mode"] == "GROUNDED_ANSWER",
        "owner_bound": package["ownership_ref"]["tenant_ref"]["id"]
        == "tenant-smoke",
        "prompt_hash_bound": len(package["prompt_contract_ref"]["content_sha256"])
        == 64,
        "policy_hash_bound": len(package["policy_snapshot_hash"]) == 64,
        "package_hash_bound": len(package["client_package_hash"]) == 64,
        "retrieval_bound": package["retrieval_package_ref"]["package_hash"]
        == "b" * 64,
        "evidence_ids_only": package["selected_evidence_ids"] == ["evidence-smoke"],
        "raw_user_excluded": "private grounded question" not in serialized,
        "raw_evidence_excluded": "private evidence" not in serialized,
        "provider_runtime_excluded": "api_key" not in serialized,
    }
    return {
        "smoke_schema_version": "ae_generation_policy_package_smoke.v1",
        "slice": "1027",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "remote_provider_required": False,
        "postgresql_required": False,
        "next_slice": "1028",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "ae_generation_policy_package="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_generation_policy_package()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
