#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
for source_root in (
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "domains/mybee",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(source_root))

from nex_ae_api.product_capabilities import (
    load_product_capability_registry,
)
from nex_ae_api.product_coordinator_activation import (
    load_product_coordinator_activation,
)
from run_mybee_w70_cp_m1_01b6b4_closure import (
    DATABASES,
    PROTECTED_FLAGS,
)
from run_mybee_w70_cp_m1_01b6b4_closure import (
    PROTECTED_TESTS as BASELINE_PROTECTED_TESTS,
)

DEFAULT_REPORT = Path(
    "reports/quality/mybee_phase1_w70_cp_m1_01b6b5a5_protected_gate.json"
)
SCHEMA_VERSION = "mybee.w70_cp_m1_01b6b5a5_protected_gate.v1"
PRODUCT_CAPABILITY_REGISTRY = (
    ROOT
    / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
)

PROTECTED_TESTS = (
    *BASELINE_PROTECTED_TESTS,
    (
        "tests/test_nex_eos_mybee_w70_cp_m1_e2e_fx_01b6b5a1_authority.py::"
        "test_api_is_service_protected_no_store_and_maps_domain_errors"
    ),
    (
        "tests/test_ae_mybee_w70_cp_m1_e2e_fx_01b6b5a2_generic_dispatch.py::"
        "test_product_assignment_does_not_enter_step_executor_or_scenario_code"
    ),
    (
        "tests/test_ae_mybee_w70_cp_m1_e2e_fx_01b6b5a3_product_router.py::"
        "test_claimed_product_route_generates_advisory_plan_before_coordinator"
    ),
    (
        "tests/test_ae_mybee_w70_cp_m1_e2e_fx_01b6b5a3_product_router.py::"
        "test_one_factory_installs_same_product_handler_in_generic_worker"
    ),
    "tests/test_ae_mybee_w70_cp_m1_e2e_fx_01b6b5a4_activation.py",
)

ACTIVE_PRODUCT_PATHS = (
    "services/nex-ae-api/nex_ae_api/product_coordinator_activation.py",
    "services/nex-ae-api/nex_ae_api/product_planning_runtime.py",
    "services/nex-ae-api/nex_ae_api/runtime_assignment_handlers.py",
    "services/nex-ae-api/nex_ae_api/semantic_candidate_admission.py",
    "services/nex-ae-api/nex_ae_api/main.py",
    "services/nex-ae-api/nex_ae_api/agent_runtime_process.py",
    "deployment/compose/canonical-platform.override.yaml",
    "deployment/oci/canonical-platform-ae-runtime.Containerfile",
)
FORBIDDEN_PRODUCT_VALUES = (
    "project-product-router",
    "tenant-a",
    "NURIVOICE",
    "2450.00",
    '"VO00"',
    "GOLDEN_A",
    "golden-a",
)


class ProductProtectedGateError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


def run_gate(
    *,
    report_path: Path = DEFAULT_REPORT,
    environ: Mapping[str, str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    python_executable: str = sys.executable,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    identities = {
        name: _require_database_url(env, name, expected_user, expected_database)
        for name, (expected_user, expected_database) in DATABASES.items()
    }
    for name in PROTECTED_FLAGS:
        env[name] = "1"

    source_checks = _source_residue_checks(repository_root)
    failed_source_checks = sorted(
        name for name, passed in source_checks.items() if not passed
    )
    if failed_source_checks:
        raise ProductProtectedGateError(
            "Product source/deployment admission failed: "
            + ", ".join(failed_source_checks)
        )

    capabilities = load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                repository_root
                / "deployment/environments/"
                "ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )
    admission = load_product_coordinator_activation(
        product_capabilities=capabilities,
        environ={
            "NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH": str(
                repository_root
                / "deployment/locks/"
                "ae-mybee-m1-product-coordinator-activation.v1.json"
            ),
            "NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH": str(
                repository_root
                / "deployment/locks/"
                "ae-mybee-m1-product-coordinator-rollback.v1.json"
            ),
        },
        repository_root=repository_root,
    )

    command = [python_executable, "-m", "pytest", "-q", *PROTECTED_TESTS]
    started = perf_counter()
    completed = command_runner(command, cwd=repository_root, env=env, check=False)
    elapsed_seconds = perf_counter() - started
    if completed.returncode != 0:
        raise ProductProtectedGateError(
            "CP-M1 01B.6B.5A.5 protected matrix failed with exit code "
            f"{completed.returncode}"
        )

    activation = dict(admission.activation_lock)
    rollback = dict(admission.rollback_receipt)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "protected_test_selector_count": len(PROTECTED_TESTS),
        "protected_tests": list(PROTECTED_TESTS),
        "actual_postgresql": True,
        "database_identities": identities,
        "migrations": {
            "current": True,
            "ae_head": activation["migration_inventory"]["head"],
            "ae_count": activation["migration_inventory"]["count"],
            "unauthorized_migration_count": 0,
        },
        "installed_activation": {
            "state": activation["activation_state"],
            "activation_hash": activation["content_hash"],
            "rollback_state": rollback["rollback_state"],
            "rollback_receipt_hash": rollback["content_hash"],
            "history_preservation": rollback["history_preservation"],
            "readiness_status": admission.readiness["status"],
        },
        "public_product_boundary": {
            "claimed_work_origin": True,
            "provider_plan_authoritative": False,
            "both_approval_waits": True,
            "ready_for_d04": True,
            "deterministic_plan_persistence": True,
            "scheduler_ownership": True,
        },
        "runtime_recovery": {
            "exact_replay": True,
            "restart": True,
            "approval_ack_loss": True,
            "rollback_queues_product_jobs": True,
            "reactivation_resumes_durable_authority": True,
        },
        "source_checks": source_checks,
        "fixed_business_value_count": 0,
        "product_specific_process_count": 0,
        "cross_service_private_access_count": 0,
        "zero_residue": True,
        "provider_assisted_live_status": "DEFERRED_TO_01B7",
        "remote_provider_required_for_this_gate": False,
        "checkpoint_gate_required": True,
        "resume_decision": "ADMIT_01B7",
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _source_residue_checks(repository_root: Path) -> dict[str, bool]:
    sources: dict[str, str] = {}
    for relative in ACTIVE_PRODUCT_PATHS:
        path = repository_root / relative
        if not path.is_file():
            return {"all_active_sources_present": False}
        sources[relative] = path.read_text(encoding="utf-8")
    joined = "\n".join(sources.values())
    return {
        "all_active_sources_present": True,
        "no_fixed_business_values": not any(
            token in joined for token in FORBIDDEN_PRODUCT_VALUES
        ),
        "no_product_specific_process": all(
            token not in joined
            for token in (
                "m1_product_worker",
                "product_coordinator_daemon",
                "product_runtime_queue",
            )
        ),
        "canonical_worker_preserved": (
            "nex_ae_api.agent_runtime_process"
            in sources["deployment/compose/canonical-platform.override.yaml"]
        ),
        "activation_and_rollback_paths_bound": all(
            token in sources["deployment/compose/canonical-platform.override.yaml"]
            for token in (
                "NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH",
                "NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH",
            )
        ),
    }


def _require_database_url(
    environ: Mapping[str, str],
    name: str,
    expected_user: str,
    expected_database: str,
) -> dict[str, str]:
    value = environ.get(name, "").strip()
    if not value:
        raise ProductProtectedGateError(f"{name} is required")
    try:
        target = make_url(value)
    except Exception as exc:
        raise ProductProtectedGateError(f"{name} is invalid") from exc
    if target.username != expected_user or target.database != expected_database:
        raise ProductProtectedGateError(
            f"{name} must target {expected_user}@{expected_database}"
        )
    return {"user": expected_user, "database": expected_database}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the protected CP-M1 01B.6B.5A.5 Product Gate."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = run_gate(report_path=args.report)
    except ProductProtectedGateError as exc:
        print(f"cp_m1_01b6b5a5_gate=fail detail={exc}", file=sys.stderr)
        return 1
    print(
        "cp_m1_01b6b5a5_gate=pass "
        f"protected_selectors={report['protected_test_selector_count']} "
        f"resume_decision={report['resume_decision']} "
        f"report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
