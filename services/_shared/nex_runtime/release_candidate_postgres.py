from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from .release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION


RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION = (
    "platform_release_candidate_postgres_restart.v1"
)
EXPECTED_DATABASE_COUNT = 5
EXPECTED_PROCESS_COUNT = 13
EXPECTED_PROCESS_GENERATIONS = 2
EXPECTED_POOL_COUNT = 10
EXPECTED_MIGRATION_GATE_COUNT = 2
EXPECTED_EVIDENCE_RECORD_COUNT = 60


def build_release_candidate_postgres_restart_evidence(
    source: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    checks = {
        "source_passed": source.get("status") == "PASS",
        "five_databases_reached": source.get("service_count")
        == EXPECTED_DATABASE_COUNT,
        "two_process_generations_ready": (
            source.get("process_count") == EXPECTED_PROCESS_COUNT
            and source.get("process_generation_count")
            == EXPECTED_PROCESS_GENERATIONS
        ),
        "fresh_pools_created": (
            source.get("pool_count_per_generation") == EXPECTED_POOL_COUNT
            and source.get("fresh_pool_count") == EXPECTED_POOL_COUNT
        ),
        "migration_gates_passed": (
            source.get("migration_gate_count") == EXPECTED_MIGRATION_GATE_COUNT
            and _positive_int(source.get("migration_count_per_generation"))
        ),
        "restart_completed": source.get("restart_count") == 1,
        "all_databases_restored": source.get("restored_count")
        == EXPECTED_DATABASE_COUNT,
        "all_sentinels_cleaned": (
            source.get("cleaned_count") == EXPECTED_DATABASE_COUNT
            and source.get("absence_count") == EXPECTED_DATABASE_COUNT
        ),
        "phase_evidence_complete": source.get("evidence_record_count")
        == EXPECTED_EVIDENCE_RECORD_COUNT,
        "runtime_stopped_in_order": source.get("shutdown_order")
        == ["runtime_processes", "postgres_pools"],
        "background_claiming_disabled": source.get("work_claiming_enabled")
        is False,
        "remote_provider_not_required": source.get("remote_provider_required")
        is False,
    }
    passed = all(checks.values())
    metrics = {
        "database_count": _safe_count(source.get("service_count")),
        "restored_database_count": _safe_count(source.get("restored_count")),
        "cleaned_database_count": _safe_count(source.get("cleaned_count")),
        "database_residue_count": max(
            0,
            EXPECTED_DATABASE_COUNT - _safe_count(source.get("absence_count")),
        ),
        "process_count": _safe_count(source.get("process_count")),
        "process_generation_count": _safe_count(
            source.get("process_generation_count")
        ),
        "migration_gate_count": _safe_count(source.get("migration_gate_count")),
        "migration_count_per_generation": _safe_count(
            source.get("migration_count_per_generation")
        ),
        "restart_count": _safe_count(source.get("restart_count")),
    }
    gate_evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": "five_database_restart",
        "status": "PASS" if passed else "FAIL",
        "execution_mode": "protected",
        "actual_execution": True,
        "private_payload_included": False,
        "observed_at": _utc_timestamp(observed_at),
        "metrics": metrics,
        "checks": checks,
    }
    gate_evidence["evidence_digest"] = _digest(gate_evidence)
    return {
        "schema_version": RELEASE_CANDIDATE_POSTGRES_SCHEMA_VERSION,
        "status": gate_evidence["status"],
        "failure_code": (
            None if passed else "release_candidate_postgres_restart_failed"
        ),
        "checks": deepcopy(checks),
        "gate_evidence": gate_evidence,
    }


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _safe_count(value: object) -> int:
    return value if _positive_int(value) else 0


def _utc_timestamp(value: datetime | None) -> str:
    observed_at = value or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
