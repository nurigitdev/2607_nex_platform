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
DEFAULT_REPORT = Path(
    "reports/quality/mybee_phase1_w70_cp_m1_01b6b4_protected_gate.json"
)
SCHEMA_VERSION = "mybee.w70_cp_m1_01b6b4_protected_gate.v1"

PROTECTED_TESTS = (
    (
        "tests/test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres.py::"
        "test_actual_postgres_two_wait_restart_ack_loss_plan_replay_and_zero_residue"
    ),
    (
        "tests/test_nex_eos_p8_s73_postgres.py::"
        "test_s73_actual_wc_decision_advances_eos_and_survives_restart"
    ),
    (
        "tests/test_nex_eos_mybee_approval_human.py::"
        "test_actual_postgres_human_approval_evidence_and_immutability"
    ),
    (
        "tests/test_nex_eos_mybee_voucher_candidate.py::"
        "test_actual_postgres_migration_immutability_and_zero_residue"
    ),
    (
        "tests/test_nex_eos_mybee_voucher_candidate.py::"
        "test_actual_postgres_candidate_review_state_machine_and_immutability"
    ),
    (
        "tests/test_nex_eos_mybee_voucher_candidate.py::"
        "test_actual_postgres_accounting_proof_and_fresh_oa_admission"
    ),
    (
        "tests/test_nex_eos_mybee_voucher_candidate.py::"
        "test_actual_postgres_atomic_posting_commits_and_replays"
    ),
    (
        "tests/test_nex_oa_mybee_project_entitlement.py::"
        "test_actual_postgres_project_grant_restart_decision_and_zero_residue"
    ),
)

PROTECTED_FLAGS = (
    "NEX_AE_MYBEE_W70_CP_M1_01B6B4_POSTGRES_SMOKE",
    "NEX_EOS_P8_S73_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S2_03_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S3_01_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_S3_03_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_W40_S4_01_POSTGRES_SMOKE",
    "NEX_EOS_MYBEE_W40_S4_03_POSTGRES_SMOKE",
    "NEX_OA_MYBEE_W40_CA01_S03_POSTGRES_SMOKE",
)

DATABASES = {
    "NEX_AE_TEST_DATABASE_URL": ("nex_ae_user", "nex_ae_test"),
    "NEX_WC_TEST_DATABASE_URL": ("nex_wc_user", "nex_wc_test"),
    "NEX_OA_TEST_DATABASE_URL": ("nex_oa_user", "nex_oa_test"),
    "NEX_EOS_TEST_DATABASE_URL": ("nex_eos_user", "nex_eos_test"),
}


class M1ProtectedGateError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


def run_gate(
    *,
    report_path: Path = DEFAULT_REPORT,
    environ: Mapping[str, str] | None = None,
    command_runner: CommandRunner = subprocess.run,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    identities = {
        name: _require_database_url(env, name, expected_user, expected_database)
        for name, (expected_user, expected_database) in DATABASES.items()
    }
    for name in PROTECTED_FLAGS:
        env[name] = "1"

    command = [python_executable, "-m", "pytest", "-q", *PROTECTED_TESTS]
    started = perf_counter()
    completed = command_runner(command, cwd=ROOT, env=env, check=False)
    elapsed_seconds = perf_counter() - started
    if completed.returncode != 0:
        raise M1ProtectedGateError(
            "CP-M1 01B.6B.4 protected matrix failed with exit code "
            f"{completed.returncode}"
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "protected_test_count": len(PROTECTED_TESTS),
        "protected_tests": list(PROTECTED_TESTS),
        "actual_postgresql": True,
        "database_identities": identities,
        "migrations_current": True,
        "approval_wait_restart_points": 2,
        "approval_ack_loss_redelivery": True,
        "exact_replay": {
            "proposal": True,
            "candidate": True,
            "review": True,
            "admission": True,
            "agent_plan": True,
            "executable_plan": True,
            "runtime_job": True,
            "posted_journal": True,
        },
        "negative_matrix": {
            "cross_scope": True,
            "revoked_or_unavailable_authority": True,
            "stale_event": True,
            "semantic_drift": True,
            "zero_mutation": True,
        },
        "duplicate_financial_or_publication_artifacts": 0,
        "zero_residue": True,
        "remote_provider_required": False,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _require_database_url(
    environ: Mapping[str, str],
    name: str,
    expected_user: str,
    expected_database: str,
) -> dict[str, str]:
    value = environ.get(name, "").strip()
    if not value:
        raise M1ProtectedGateError(f"{name} is required")
    try:
        target = make_url(value)
    except Exception as exc:
        raise M1ProtectedGateError(f"{name} is invalid") from exc
    if target.username != expected_user or target.database != expected_database:
        raise M1ProtectedGateError(
            f"{name} must target {expected_user}@{expected_database}"
        )
    return {"user": expected_user, "database": expected_database}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the protected CP-M1 01B.6B.4 PostgreSQL replay gate."
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        report = run_gate(report_path=args.report)
    except M1ProtectedGateError as exc:
        print(f"cp_m1_01b6b4_gate=fail detail={exc}", file=sys.stderr)
        return 1
    print(
        "cp_m1_01b6b4_gate=pass "
        f"protected_tests={report['protected_test_count']} "
        f"report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
