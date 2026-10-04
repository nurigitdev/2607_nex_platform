#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-ag"))

from nex_runtime.ag_projection_policy import resolve_ag_projection_policy  # noqa: E402
from nex_runtime.runtime_profiles import runtime_profile_environment_overlay  # noqa: E402
from nex_ag.operations import (  # noqa: E402
    OperationsSourceConfigError,
    build_ag_operations_source_runtime,
)
from nex_ag.processing_operations import (  # noqa: E402
    build_cx_processing_run_operation_stores,
)
from nex_ag.remediation_execution_operations import (  # noqa: E402
    build_remediation_execution_operation_stores,
)
from nex_ag.retrieval_operations import (  # noqa: E402
    build_retrieval_package_operation_stores,
)


LEGACY_ADAPTER_PATHS = (
    "services/nex-ag/nex_ag/operations.py",
    "services/nex-ag/nex_ag/processing_operations.py",
    "services/nex-ag/nex_ag/retrieval_operations.py",
    "services/nex-ag/nex_ag/remediation_execution_operations.py",
)


def run_platform_ag_projection_policy() -> dict[str, Any]:
    local_policy = resolve_ag_projection_policy(
        "memory", environ={"NEX_PROFILE": "local_mock"}
    )
    protected_policy = resolve_ag_projection_policy(
        "api", environ={"NEX_PROFILE": "test"}
    )
    legacy_policy = resolve_ag_projection_policy("postgres", environ={})
    rejection = None
    try:
        build_ag_operations_source_runtime(
            environ={
                "NEX_PROFILE": "production",
                "NEX_AG_OPERATIONS_SOURCE_MODE": "postgres",
            }
        )
    except OperationsSourceConfigError as exc:
        rejection = str(exc)

    api_environment = {
        **runtime_profile_environment_overlay("test"),
        "NEX_AG_OPERATIONS_SOURCE_PROFILE": "test",
        "NEX_AG_OPERATIONS_SOURCE_SERVICES": "nex-cx",
    }
    api_runtime = build_ag_operations_source_runtime(environ=api_environment)
    api_stores = {
        "processing": build_cx_processing_run_operation_stores(
            runtime=api_runtime, environ=api_environment
        ),
        "retrieval": build_retrieval_package_operation_stores(
            runtime=api_runtime, environ=api_environment
        ),
        "remediation": build_remediation_execution_operation_stores(
            runtime=api_runtime, environ=api_environment
        ),
    }
    legacy_adapters = [
        path
        for path in LEGACY_ADAPTER_PATHS
        if "ag_operations_source_database_env(" in (ROOT / path).read_text(encoding="utf-8")
    ]
    checks = {
        "local_mock_requires_memory_projection": local_policy.mode == "memory"
        and local_policy.legacy_database_adapter_allowed is False,
        "protected_profile_requires_api_projection": protected_policy.mode == "api"
        and protected_policy.protected is True,
        "protected_profile_rejects_postgres_projection": rejection is not None,
        "legacy_postgres_is_unmanaged_compatibility_only": (
            legacy_policy.managed_profile is None
            and legacy_policy.legacy_database_adapter_allowed is True
        ),
        "api_runtime_does_not_open_database_registry": api_runtime.registry is None,
        "api_runtime_does_not_fall_back_to_memory_stores": all(
            not stores for stores in api_stores.values()
        ),
        "legacy_database_adapters_are_inventoried": len(legacy_adapters) == 4,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "platform_ag_projection_policy.v1",
        "slice": "1318",
        "requirement": "S132",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_ag_projection_policy_failed",
        "checks": checks,
        "issues": [name for name, value in checks.items() if not value],
        "protected_policy": protected_policy.to_public_projection(),
        "api_runtime": api_runtime.to_summary(),
        "legacy_adapter_paths": legacy_adapters,
        "decision": {
            "protected_cross_service_database_reads_allowed": False,
            "api_mode_memory_fallback_allowed": False,
            "legacy_adapter_removal_requirement": "S138",
            "next_slice": "1319",
        },
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"platform_ag_projection_policy=fail issues={len(evidence.get('issues') or [])}"
    return (
        "platform_ag_projection_policy=pass "
        f"protected={evidence.get('protected_policy', {}).get('mode')} "
        f"legacy_adapters={len(evidence.get('legacy_adapter_paths') or [])} "
        f"next={evidence.get('decision', {}).get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_platform_ag_projection_policy()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
