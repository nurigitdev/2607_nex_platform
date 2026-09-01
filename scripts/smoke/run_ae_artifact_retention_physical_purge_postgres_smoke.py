#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_artifact_retention_purge_postgres_smoke as purge_pg  # noqa: E402


SCHEMA_VERSION = "ae_artifact_retention_physical_purge_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_ARTIFACT_RETENTION_PHYSICAL_PURGE_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = purge_pg.SERVICE_ID
DEFAULT_PROFILE = purge_pg.DEFAULT_PROFILE


def run_ae_artifact_retention_physical_purge_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "default_quality_gate_behavior": "skipped_until_explicitly_enabled",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for physical purge smoke.",
            profile=profile,
            env=env,
        )

    delegated_env = dict(env)
    delegated_env[purge_pg.SMOKE_ENV] = "1"
    delegated_env[purge_pg.SMOKE_PROFILE_ENV] = profile
    source = purge_pg.run_ae_artifact_retention_purge_postgres_smoke(delegated_env)
    if source.get("status") != "PASS":
        return _failure(
            "underlying_purge_smoke_failed",
            str(source.get("failure_code") or source.get("status") or "unknown"),
            profile=profile,
            env=env,
        )

    checks = _physical_purge_checks(source)
    failed_checks = [key for key, passed in checks.items() if not passed]
    if failed_checks:
        return _failure(
            "physical_purge_checks_failed",
            ", ".join(failed_checks),
            profile=profile,
            env=env,
        )

    retention = source["retention"]
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": source["database_env"],
        "redacted_database_url": source["redacted_database_url"],
        "source_smoke_schema_version": source["smoke_schema_version"],
        "migration": dict(source["migration"]),
        "physical_purge": {
            "storage_adapter": "rendered_artifact_storage",
            "database_adapter": "artifact_graph_child_first",
            "storage_delete_order": "before_database_rows",
            "approval_gate": "operator_approval_required",
            "handoff_lineage_retained": True,
        },
        "retention": {
            "approval_blocked_status": retention["approval_blocked_status"],
            "approval_blocked_reason": retention["approval_blocked_reason"],
            "executed_selected_count": retention["executed_selected_count"],
            "deleted_counts": dict(retention["deleted_counts"]),
        },
        "materialized_file_count": dict(source["materialized_file_count"]),
        "db_before": dict(source["db_before"]),
        "db_after_execute": dict(source["db_after_execute"]),
        "cleanup": dict(source["cleanup"]),
        "checks": checks,
        "live_db": source["live_db"] is True,
    }
    purge_pg.assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def _physical_purge_checks(source: Mapping[str, Any]) -> dict[str, bool]:
    retention = _mapping(source.get("retention"))
    deleted_counts = _mapping(retention.get("deleted_counts"))
    materialized_file_count = _mapping(source.get("materialized_file_count"))
    db_before = _mapping(source.get("db_before"))
    db_after_execute = _mapping(source.get("db_after_execute"))
    cleanup = _mapping(source.get("cleanup"))
    checks = _mapping(source.get("checks"))
    return {
        "source_smoke_passed": source.get("status") == "PASS",
        "live_db": source.get("live_db") is True,
        "operator_approval_gate_blocked": (
            retention.get("approval_blocked_status") == "BLOCKED"
            and retention.get("approval_blocked_reason")
            == "operator_approval_required"
        ),
        "storage_adapter_deleted_files": deleted_counts.get("storage_files") == 2,
        "database_adapter_deleted_artifact": deleted_counts.get("artifacts") == 1,
        "database_adapter_deleted_child_rows": (
            deleted_counts.get("files") == 2 and deleted_counts.get("links") == 4
        ),
        "storage_and_database_counts_reported_separately": (
            "storage_files" in deleted_counts and "files" in deleted_counts
        ),
        "materialized_storage_removed": (
            materialized_file_count.get("before") == 4
            and materialized_file_count.get("after_execute") == 2
        ),
        "database_candidate_removed": (
            db_before.get("candidate_rows") == 1
            and db_after_execute.get("candidate_rows") == 0
        ),
        "handoff_lineage_retained": db_after_execute.get("handoff_rows") == 2,
        "cleanup_completed": (
            cleanup.get("artifacts") == 1 and cleanup.get("handoffs") == 2
        ),
        "underlying_metadata_only": checks.get("metadata_only_evidence") is True,
        "approval_blocked_rows_retained": (
            checks.get("approval_blocked_rows_retained") is True
        ),
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    env: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": purge_pg._safe_detail(detail, env),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = evidence.get("status")
    if status == "SKIPPED":
        return (
            "ae_artifact_retention_physical_purge_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if status != "PASS":
        return (
            "ae_artifact_retention_physical_purge_postgres_smoke=fail "
            f"service={SERVICE_ID} reason={evidence.get('failure_code')}"
        )
    retention = _mapping(evidence.get("retention"))
    deleted_counts = _mapping(retention.get("deleted_counts"))
    return (
        "ae_artifact_retention_physical_purge_postgres_smoke=pass "
        f"service={SERVICE_ID} db_env={evidence.get('database_env')} "
        f"deleted_artifacts={deleted_counts.get('artifacts')} "
        f"deleted_storage_files={deleted_counts.get('storage_files')} "
        f"approval_blocked={retention.get('approval_blocked_reason')} "
        f"live_db={str(evidence.get('live_db')).lower()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention physical purge PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    evidence = run_ae_artifact_retention_physical_purge_postgres_smoke()
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
