#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_postgresql_resilience_boundary.v1"
CANONICAL_PATH = "docs/53_platform_postgresql_resilience_disaster_recovery.md"
S143_ATTESTATION_PATH = "deployment/security/s143-external-staging-attestation.json"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
RUNNER_NAME = "run_s145_postgresql_resilience_boundary.py"


@dataclass(frozen=True)
class PostgresResilienceGap:
    gap_id: str
    owner: str
    target_slices: tuple[str, ...]


POSTGRES_RESILIENCE_GAPS = (
    PostgresResilienceGap("single_host_dr_boundary", "platform_and_database_owners", ("1443",)),
    PostgresResilienceGap("backup_policy_contract", "platform_and_database_owners", ("1444",)),
    PostgresResilienceGap("logical_backup_execution", "database_owners", ("1445",)),
    PostgresResilienceGap("isolated_restore_guard", "database_owners_and_platform", ("1446",)),
    PostgresResilienceGap("catalog_integrity_retention", "platform", ("1447",)),
    PostgresResilienceGap("cluster_pitr_recovery", "postgres_operator_and_platform", ("1448",)),
    PostgresResilienceGap("restart_safe_backup_worker", "platform", ("1449",)),
    PostgresResilienceGap(
        "compose_rehearsal_acceptance_closure",
        "platform_and_database_owners",
        ("1450", "1451", "1452"),
    ),
)

REQUIRED_PATHS = (
    "docs/48_platform_production_readiness_plan.md",
    "docs/40_platform_postgresql_restart_orchestration.md",
    CANONICAL_PATH,
    "docs/slices/1443_s145_postgresql_resilience_boundary.md",
    "deployment/compose/s143-staging.compose.yaml",
    S143_ATTESTATION_PATH,
    "services/_shared/nex_runtime/database.py",
    "services/_shared/nex_runtime/postgres_orchestration.py",
    "scripts/db/run_migrations.py",
    "scripts/smoke/run_platform_postgres_restart_smoke.py",
    "scripts/smoke/run_s133_platform_postgres_restart_closure.py",
    QUALITY_GATE_PATH,
)


def run_postgresql_resilience_boundary(root: Path = ROOT) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    canonical = " ".join(_read_text(root / CANONICAL_PATH).split())
    readiness = " ".join(_read_text(root / "docs/48_platform_production_readiness_plan.md").split())
    database = _read_text(root / "services/_shared/nex_runtime/database.py")
    migrations = _read_text(root / "scripts/db/run_migrations.py")
    restart = _read_text(root / "scripts/smoke/run_s133_platform_postgres_restart_closure.py")
    compose = _read_text(root / "deployment/compose/s143-staging.compose.yaml")
    quality_gate = _read_text(root / QUALITY_GATE_PATH)
    attestation = _read_json(root / S143_ATTESTATION_PATH)
    checks = {
        "required_paths_present": all(paths.values()),
        "s143_dependency_accepted": (
            attestation.get("requirement_id") == "S143"
            and attestation.get("actual_execution") is True
            and all(attestation.get("checks", {}).values())
            and attestation.get("privacy", {}).get("violation_count") == 0
            and attestation.get("rollback", {}).get("drill_status") == "PASS"
        ),
        "five_service_database_owners_present": all(
            token in migrations for token in ('"nex-oa"', '"nex-ag"', '"nex-ae-api"', '"nex-cx"', '"nex-mo"')
        ),
        "pool_resilience_controls_present": all(
            token in database for token in (
                "pool_size", "max_overflow", "pool_timeout_seconds",
                "pool_recycle_seconds", "pool_pre_ping", "statement_timeout_ms",
            )
        ),
        "restart_foundation_present": (
            "run_s133_platform_postgres_restart_closure" in restart
            and "platform_postgres_restart" in restart
        ),
        "single_host_compose_database_edge_present": (
            "host.docker.internal:host-gateway" in compose
            and "NEX_OA_DATABASE_URL_REF" in compose
            and "NEX_MO_DATABASE_URL_REF" in compose
        ),
        "no_ha_cold_recovery_decision_frozen": all(
            token in canonical for token in (
                "High availability is not part of S145",
                "operator-controlled cold-recovery", "automatic failover",
                "explicitly outside S145",
            )
        ),
        "logical_and_pitr_recovery_split_frozen": all(
            token in canonical for token in (
                "custom-format logical backups", "physical base backup plus WAL archive",
                "PITR restores the whole PostgreSQL cluster",
            )
        ),
        "rpo_rto_and_retention_frozen": all(
            token in canonical for token in (
                "6 hours", "30 minutes", "60 minutes", "28 restore points",
                "2 verified generations",
            )
        ),
        "eight_gaps_documented": (
            len(POSTGRES_RESILIENCE_GAPS) == 8
            and all(f"`{item.gap_id}`" in canonical for item in POSTGRES_RESILIENCE_GAPS)
        ),
        "ten_slice_sequence_and_gates_frozen": (
            all(f"`{slice_id}`" in canonical for slice_id in range(1443, 1453))
            and "Checkpoint Gate at Slice 1447" in canonical
            and "Full Gate at Slice 1452" in canonical
        ),
        "production_deferral_remains_explicit": (
            "production deployment remains unapproved" in canonical.lower()
            and "production_postgresql_backup_ha_dr" in readiness
            and "DEFERRED" in readiness
        ),
        "privacy_restore_and_quality_guards_frozen": (
            "database URL or password must appear" in canonical
            and "restore can address the active source target" in canonical
            and quality_gate.count(RUNNER_NAME) == 1
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items() if not present
    ]
    issues.extend(
        {"category": "check_failed", "check": name}
        for name, passed in checks.items() if not passed
    )
    passed = not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1443",
        "requirement": "S145",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "gaps": [
            {"gap_id": item.gap_id, "owner": item.owner, "target_slices": list(item.target_slices), "state": "OPEN"}
            for item in POSTGRES_RESILIENCE_GAPS
        ],
        "summary": {
            "required_path_count": sum(paths.values()),
            "check_count": len(checks), "gap_count": len(POSTGRES_RESILIENCE_GAPS),
            "slice_count": 10, "database_count": 5,
            "missing_path_count": sum(not value for value in paths.values()),
        },
        "decision": {
            "single_host_compose_feasible": True,
            "high_availability_in_scope": False,
            "automatic_failover_in_scope": False,
            "recovery_mode": "OPERATOR_CONTROLLED_COLD_RECOVERY",
            "service_recovery": "LOGICAL_CUSTOM_ARCHIVE",
            "cluster_recovery": "BASE_BACKUP_WAL_PITR",
            "protected_source_profile": "FIVE_TEST_DATABASES_READ_ONLY",
            "isolated_restore_required": True,
            "production_backup_mount_required": True,
            "production_connection_required": False,
            "production_deployment_approved": False,
            "new_table_required": False,
            "next_slice": "1444" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return f"postgresql_resilience_boundary=fail issues={len(result.get('issues') or [])}"
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "postgresql_resilience_boundary=pass "
        f"checks={summary.get('check_count', 0)}/13 "
        f"databases={summary.get('database_count', 0)} "
        f"gaps={summary.get('gap_count', 0)} "
        f"ha={str(decision.get('high_availability_in_scope')).lower()} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_postgresql_resilience_boundary()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

