#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path("reports/quality/mybee_phase1_w60_s7_03a_closure.json")
DEFAULT_PERFORMANCE_REPORT = Path(
    "reports/quality/mybee_phase1_w60_s7_03a_performance.json"
)
SCHEMA_VERSION = "mybee.w60_s7_03a_closure.v1"

PROTECTED_TESTS = (
    (
        "tests/test_nex_eos_mybee_project_pnl_projector_pg.py::"
        "test_actual_postgres_direct_allocation_projector_rebuild_and_replay"
    ),
    (
        "tests/test_nex_eos_mybee_payroll_labor_bridge_pg.py::"
        "test_actual_postgres_payroll_labor_bridge_replay_privacy_and_immutability"
    ),
    (
        "tests/test_nex_eos_mybee_payroll_project_allocation_pg.py::"
        "test_actual_postgres_labor_adjustment_residual_and_pnl_rebuild"
    ),
    (
        "tests/test_nex_eos_mybee_material_commitment_pg.py::"
        "test_actual_postgres_material_commitment_projection_and_immutability"
    ),
    (
        "tests/test_nex_eos_mybee_material_consumption_pg.py::"
        "test_actual_postgres_material_consumption_release_and_pnl_reconciliation"
    ),
    (
        "tests/test_nex_eos_mybee_project_pnl_query_pg.py::"
        "test_actual_postgres_authorized_query_and_mybee_consumer_zero_residue"
    ),
    (
        "tests/test_nex_eos_mybee_pnl_privacy_pg.py::"
        "test_actual_postgres_privacy_guard_replay_and_zero_residue"
    ),
    (
        "tests/test_nex_oa_mybee_project_entitlement.py::"
        "test_actual_postgres_project_grant_restart_decision_and_zero_residue"
    ),
)

PROTECTED_FLAGS = (
    "NEX_EOS_MYBEE_S7_02A_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_02B_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_02C_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_02D_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_02E_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_02F_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S7_03_POSTGRES_SMOKE",
    "NEX_OA_MYBEE_W40_CA01_S03_POSTGRES_SMOKE",
)


class W60ClosureError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


def run_closure(
    *,
    report_path: Path = DEFAULT_REPORT,
    performance_report_path: Path = DEFAULT_PERFORMANCE_REPORT,
    environ: Mapping[str, str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    _require_database_url(env, "NEX_EOS_TEST_DATABASE_URL", "nex_eos_test")
    _require_database_url(env, "NEX_OA_TEST_DATABASE_URL", "nex_oa_test")
    for name in PROTECTED_FLAGS:
        env[name] = "1"
    env["NEX_MYBEE_W60_PERFORMANCE_REPORT"] = str(performance_report_path)

    command = _pytest_command(python_executable)
    started = perf_counter()
    completed = command_runner(command, cwd=ROOT, env=env, check=False)
    elapsed_seconds = perf_counter() - started
    if completed.returncode != 0:
        raise W60ClosureError(
            f"W60 protected PostgreSQL matrix failed with exit code "
            f"{completed.returncode}"
        )

    performance = _load_performance_report(performance_report_path)
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "protected_test_count": len(PROTECTED_TESTS),
        "protected_tests": list(PROTECTED_TESTS),
        "actual_postgresql": True,
        "databases": ["nex_eos_test", "nex_oa_test"],
        "project_authorization_action": "project:pnl:read",
        "direct_allocation_rebuild": True,
        "payroll_actual_and_adjustment": True,
        "material_commitment_and_consumption": True,
        "privacy_guard_and_mybee_admission": True,
        "restart_rebuild_exact_replay": performance["restart_rebuild_exact_replay"],
        "performance": performance,
        "query_plan_recorded": bool(performance["projection_index_names"]),
        "zero_residue": True,
        "remote_provider_required": False,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _pytest_command(python_executable: str) -> list[str]:
    return [python_executable, "-m", "pytest", "-q", *PROTECTED_TESTS]


def _require_database_url(
    environ: Mapping[str, str], name: str, expected_database: str
) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise W60ClosureError(f"{name} is required")
    if f"/{expected_database}" not in value:
        raise W60ClosureError(
            f"{name} must target the protected {expected_database} database"
        )
    return value


def _load_performance_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise W60ClosureError("W60 performance evidence was not produced")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise W60ClosureError("W60 performance evidence is malformed") from exc
    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise W60ClosureError("W60 performance evidence did not pass")
    required = {
        "rebuild_p95_ms",
        "rebuild_p95_budget_ms",
        "read_p95_ms",
        "read_p95_budget_ms",
        "projection_index_names",
        "restart_rebuild_exact_replay",
        "actual_population_evidence",
    }
    if not required.issubset(value):
        raise W60ClosureError("W60 performance evidence fields are incomplete")
    if float(value["rebuild_p95_ms"]) > float(value["rebuild_p95_budget_ms"]):
        raise W60ClosureError("W60 rebuild p95 exceeded its budget")
    if float(value["read_p95_ms"]) > float(value["read_p95_budget_ms"]):
        raise W60ClosureError("W60 protected read p95 exceeded its budget")
    if not value["restart_rebuild_exact_replay"]:
        raise W60ClosureError("W60 restart rebuild did not converge")
    if not value["actual_population_evidence"]:
        raise W60ClosureError("W60 privacy evidence was not source-backed")
    indexes = value["projection_index_names"]
    if not isinstance(indexes, Sequence) or "ix_eos_project_pnl_lookup" not in indexes:
        raise W60ClosureError("W60 Project-period lookup index was not observed")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the protected MyBee W60 Project P&L closure matrix."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--performance-report",
        type=Path,
        default=DEFAULT_PERFORMANCE_REPORT,
    )
    parser.add_argument("--summary", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = run_closure(
            report_path=args.report,
            performance_report_path=args.performance_report,
        )
    except W60ClosureError as exc:
        print(f"w60_closure=fail detail={exc}", file=sys.stderr)
        return 1
    performance = report["performance"]
    print(
        "w60_closure=pass "
        f"protected_tests={report['protected_test_count']} "
        f"rebuild_p95_ms={performance['rebuild_p95_ms']} "
        f"read_p95_ms={performance['read_p95_ms']} "
        f"report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
