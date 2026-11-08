#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p5_s5_postgres_smoke as p5_s5
import run_p6_ca02_s3_in_process_smoke as p6_ca02_s3
import run_p6_s7_postgres_smoke as p6_s7
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_runtime import load_env_file, redact_database_url
from run_migrations import run_service_migrations

SCHEMA_VERSION = "p6_ca02_s7_dual_profile_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_P6_CA02_S7_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
NSL_SOURCE_ENV = "NEX_AE_P6_CA02_S7_NSL_SOURCE"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_MIGRATION = "2205_ae_nsl_dual_profile"
DEFAULT_REPORT = ROOT / "reports/smoke/p6-ca02-s7-dual-profile-postgres.json"
PROFILES = (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)


def run_p6_ca02_s7_dual_profile_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S7",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not p5_s5._target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )
    source_value = env.get(NSL_SOURCE_ENV, "")
    if not source_value:
        return _failure("nsl_source_missing", f"{NSL_SOURCE_ENV} is required.")

    try:
        nsl_source = Path(source_value).resolve(strict=True)
        lock = json.loads(p6_ca02_s3.DEFAULT_LOCK.read_text(encoding="utf-8"))
        package = p6_ca02_s3._installed_package_evidence(nsl_source, lock)
        migration = run_service_migrations(
            "nex-ae-api", database_url=database_url, profile="test"
        )
        profile_evidence = {
            profile: p6_s7.execute_p6_s7_postgres_profile(
                database_url=database_url,
                nsl_source=nsl_source,
                backend_profile=profile,
            )
            for profile in PROFILES
        }
        parity = _compare_profile_contracts(profile_evidence)
        checks = {
            "migration_current": (
                REQUIRED_MIGRATION in migration.planned
                and migration.planned[-1] == REQUIRED_MIGRATION
                and len(migration.planned)
                == len(migration.applied) + len(migration.skipped)
            ),
            "admitted_installed_wheel": (
                package["wheel_sha256"] == lock["wheel_sha256"]
                and package["package_version"] == lock["package_version"]
                and package["public_api_complete"] is True
                and package["runtime_import_is_not_checkout"] is True
            ),
            "in_process_postgres_e2e": _profile_passed(
                profile_evidence[NSL_V01_IN_PROCESS_BACKEND],
                NSL_V01_IN_PROCESS_BACKEND,
            ),
            "process_isolated_postgres_e2e": _profile_passed(
                profile_evidence[NSL_V01_PROCESS_ISOLATED_BACKEND],
                NSL_V01_PROCESS_ISOLATED_BACKEND,
            ),
            "skill_execution_request_parity": parity["request"],
            "nsl_result_summary_parity": parity["result_summary"],
            "runtime_result_semantic_parity": parity["runtime_result"],
            "step_result_v1_2_parity": parity["step_result"],
            "identity_lineage_preserved_per_profile": parity["identity_lineage"],
            "zero_residue_both_profiles": all(
                int(evidence["cleanup_counts"].get("remaining", -1)) == 0
                and int(evidence["cleanup_counts"].get("s7_remaining", -1)) == 0
                for evidence in profile_evidence.values()
            ),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "P6-CA02-S7",
            "status": status,
            "failure_code": None if status == "PASS" else "dual_profile_parity_failed",
            "actual_postgres": True,
            "remote_provider_required": False,
            "database_env": DATABASE_ENV,
            "redacted_database_url": redact_database_url(database_url),
            "nsl_source_revision": lock["source_revision"],
            "package": package,
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
                "latest_version": migration.planned[-1],
            },
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "profile_checks": {
                profile: dict(evidence["checks"])
                for profile, evidence in profile_evidence.items()
            },
            "profile_row_counts": {
                profile: dict(evidence["row_counts"])
                for profile, evidence in profile_evidence.items()
            },
            "profile_cleanup_counts": {
                profile: dict(evidence["cleanup_counts"])
                for profile, evidence in profile_evidence.items()
            },
            "parity": parity,
        }
    except Exception as exc:  # noqa: BLE001 - protected smoke contains the boundary
        return _failure(
            "execution_failed",
            p5_s5._redact_detail(str(exc), database_url=database_url),
        )


def _profile_passed(evidence: Mapping[str, Any], expected_profile: str) -> bool:
    return (
        evidence.get("status") == "PASS"
        and evidence.get("actual_postgres") is True
        and evidence.get("backend_profile") == expected_profile
        and all(bool(value) for value in dict(evidence.get("checks") or {}).values())
    )


def _compare_profile_contracts(
    profile_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, bool]:
    in_process = dict(profile_evidence[NSL_V01_IN_PROCESS_BACKEND]["parity_contract"])
    isolated = dict(
        profile_evidence[NSL_V01_PROCESS_ISOLATED_BACKEND]["parity_contract"]
    )
    return {
        "request": in_process["request_fields"] == isolated["request_fields"]
        and in_process["request_projection"] == isolated["request_projection"],
        "result_summary": in_process["result_summary_fields"]
        == isolated["result_summary_fields"]
        and in_process["result_summary_projection"]
        == isolated["result_summary_projection"],
        "runtime_result": in_process["runtime_result_projection"]
        == isolated["runtime_result_projection"],
        "step_result": in_process["step_result_fields"]
        == isolated["step_result_fields"]
        and in_process["step_result_projection"] == isolated["step_result_projection"],
        "identity_lineage": in_process["identity_lineage_preserved"] is True
        and isolated["identity_lineage_preserved"] is True,
    }


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "P6-CA02-S7",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = dict(evidence.get("checks") or {})
    migration = dict(evidence.get("migration") or {})
    parity = dict(evidence.get("parity") or {})
    return (
        "p6_ca02_s7_dual_profile_postgres="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"actual_postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"parity={sum(bool(value) for value in parity.values())}/{len(parity)} "
        f"latest_migration={migration.get('latest_version', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run P6-CA02-S7 dual-profile PostgreSQL E2E parity smoke"
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_env_file(ROOT / ".env.local")
    evidence = run_p6_ca02_s7_dual_profile_postgres_smoke()
    if evidence["status"] != "SKIPPED":
        DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_REPORT.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
