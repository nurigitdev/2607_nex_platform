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
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "services" / "nex-oa",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p8_s65_golden_a_approval_journey as p8_s65
import run_p8_s66_golden_a_eos_commit_journey as p8_s66

SCHEMA_VERSION = "p8_s67_golden_a_exactly_once.v1"
SMOKE_ENV = "NEX_P8_S67_GOLDEN_A_EXACTLY_ONCE_LIVE"
DEFAULT_REPORT = Path("/tmp/nex-p8-s67-golden-a-exactly-once.json")
EXPECTED_DATABASES = p8_s66.EXPECTED_DATABASES


class P8S67SmokeError(RuntimeError):
    pass


def run_p8_s67_golden_a_exactly_once(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = p8_s65.DEFAULT_SOURCE,
    lock_path: Path = p8_s65.DEFAULT_LOCK,
    wheel_directory: Path = p8_s65.DEFAULT_WHEEL_DIRECTORY,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S67",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
            "actual_postgres": False,
            "actual_remote_provider": False,
        }
    database_urls = {key: env.get(key, "") for key in EXPECTED_DATABASES}
    try:
        for key, (role, database) in EXPECTED_DATABASES.items():
            p8_s65._require_database_target(
                database_urls[key], role=role, database=database, label=key
            )
        s65 = p8_s65.run_p8_s65_golden_a_approval_journey(
            {**env, p8_s65.SMOKE_ENV: "1"},
            execute=True,
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            python_bin=python_bin,
        )
        if s65.get("status") != "PASS":
            raise P8S67SmokeError("P8-S65 live approval prerequisite failed")
        eos_migration = p8_s66.run_service_migrations(
            "nex-eos",
            database_url=database_urls[p8_s66.EOS_DATABASE_ENV],
            profile="test",
        )
        commit = p8_s66._execute_commit(
            env=env,
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            python_bin=python_bin,
            ae_database_url=database_urls[p8_s65.AE_DATABASE_ENV],
            oa_database_url=database_urls[p8_s65.OA_DATABASE_ENV],
            eos_database_url=database_urls[p8_s66.EOS_DATABASE_ENV],
            s65=s65,
            exactly_once=True,
        )
        approval = s65["approval"]
        approval_evidence = approval["platform_approval_evidence"]
        write_identity = approval["write_identity"]
        migration_heads = {
            service: summary["latest_version"]
            for service, summary in s65["migrations"].items()
        }
        migration_heads["nex-eos"] = p8_s65._migration_summary(eos_migration)[
            "latest_version"
        ]
        checks = {
            "s65_live_approval_passed": s65["status"] == "PASS",
            "eos_migrations_current": (
                len(eos_migration.planned)
                == len(eos_migration.applied) + len(eos_migration.skipped)
            ),
            "duplicate_approval_event_idempotent": (
                approval["event_replay"]["created"] is False
                and approval["event_replay"]["resume_runtime_job_id"]
                == approval["resume_enqueue_replay"]["runtime_job_id"]
            ),
            "duplicate_resume_enqueue_idempotent": approval["resume_job_count"] == 1,
            **commit["checks"],
        }
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S67",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "nsl_release": s65["release"],
            "migration_heads": migration_heads,
            "nsl_execution_id": write_identity["nsl_execution_id"],
            "approval_work_item_id": approval_evidence["approval_work_item_ref"],
            "s65": {
                "status": s65["status"],
                "payload_hash": approval["payload_hash"],
                "approval_event_replayed": approval["event_replay"]["created"] is False,
                "resume_job_count": approval["resume_job_count"],
                "model_ref": s65["provider"]["model_ref"],
            },
            "eos_migration": p8_s65._migration_summary(eos_migration),
            **{key: value for key, value in commit.items() if key != "checks"},
            "checks": checks,
            "checks_passed": sum(bool(value) for value in checks.values()),
            "checks_total": len(checks),
            "decision": {
                "p8_s67_closed": all(checks.values()),
                "business_mutation_count": commit["eos_mutation_counts"][
                    "eos_voucher_draft"
                ],
                "next_slice": "P8-S68",
            },
        }
        p8_s65._assert_redacted(evidence, env)
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected gate records safe failure.
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S67",
            "status": "FAIL",
            "actual_postgres": False,
            "actual_remote_provider": False,
            "failure_code": getattr(exc, "error_code", type(exc).__name__),
            "detail": p8_s65._redact(str(exc), *database_urls.values()),
            "decision": {"p8_s67_closed": False},
        }
        p8_s65._assert_redacted(evidence, env)
        return evidence


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks", {})
    passed = sum(bool(value) for value in checks.values())
    decision = evidence.get("decision", {})
    return (
        "p8_s67_golden_a_exactly_once="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(evidence.get('actual_postgres'))).lower()} "
        f"provider={str(bool(evidence.get('actual_remote_provider'))).lower()} "
        f"checks={passed}/{len(checks)} "
        f"mutations={decision.get('business_mutation_count', '-')}"
    )


def write_report(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected P8-S67 Golden A exactly-once variants."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=p8_s65.DEFAULT_SOURCE)
    parser.add_argument("--lock", type=Path, default=p8_s65.DEFAULT_LOCK)
    parser.add_argument(
        "--wheel-directory", type=Path, default=p8_s65.DEFAULT_WHEEL_DIRECTORY
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    evidence = run_p8_s67_golden_a_exactly_once(
        execute=args.execute,
        source=args.source,
        lock_path=args.lock,
        wheel_directory=args.wheel_directory,
        python_bin=args.python,
    )
    write_report(args.report, evidence)
    print(summary_line(evidence))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
