from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable


POSTGRES_SERVICE_ORDER = (
    "nex-oa",
    "nex-mo",
    "nex-cx",
    "nex-ae-api",
    "nex-ag",
)
POSTGRES_ORCHESTRATION_PHASES = (
    "CONFIGURATION",
    "MIGRATION",
    "POOL_READINESS",
    "STARTUP",
    "SHUTDOWN",
    "RESTART",
    "RESTORATION",
    "CLEANUP",
)
POSTGRES_EVIDENCE_STATUSES = ("PENDING", "RUNNING", "PASSED", "FAILED")
POSTGRES_RUN_STATES = (
    "NEW",
    "RUNNING",
    "RESTARTING",
    "PASSED",
    "FAILED",
)
POOL_WORKLOADS = ("api", "worker")
_SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


class PostgresOrchestrationEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class PostgresOrchestrationPlan:
    schema_version: str
    requirement: str
    profile: str
    service_order: tuple[str, ...]
    phase_order: tuple[str, ...]
    pool_workloads: tuple[str, ...]
    restart_count: int
    production_database_allowed: bool
    remote_provider_required: bool

    def to_public_projection(self) -> dict[str, Any]:
        validate_postgres_orchestration_plan(self)
        return asdict(self)


@dataclass(frozen=True)
class PostgresPhaseEvidence:
    service_id: str
    phase: str
    status: str
    restart_iteration: int
    evidence_codes: tuple[str, ...]
    duration_ms: int
    failure_code: str | None = None


@dataclass(frozen=True)
class PlatformPostgresRestartEvidence:
    run_id: str
    state: str
    records: tuple[PostgresPhaseEvidence, ...]

    def to_public_projection(self) -> dict[str, Any]:
        validate_platform_postgres_restart_evidence(self)
        status_counts = Counter(record.status for record in self.records)
        return {
            "schema_version": "platform_postgres_restart_evidence.v1",
            "requirement": "S133",
            "profile": "test",
            "run_id": self.run_id,
            "state": self.state,
            "service_count": len({record.service_id for record in self.records}),
            "record_count": len(self.records),
            "status_counts": {
                status: status_counts.get(status, 0)
                for status in POSTGRES_EVIDENCE_STATUSES
            },
            "records": [asdict(record) for record in self.records],
        }


S133_POSTGRES_ORCHESTRATION_PLAN = PostgresOrchestrationPlan(
    schema_version="platform_postgres_orchestration_plan.v1",
    requirement="S133",
    profile="test",
    service_order=POSTGRES_SERVICE_ORDER,
    phase_order=POSTGRES_ORCHESTRATION_PHASES,
    pool_workloads=POOL_WORKLOADS,
    restart_count=1,
    production_database_allowed=False,
    remote_provider_required=False,
)


def validate_postgres_orchestration_plan(
    plan: PostgresOrchestrationPlan,
) -> None:
    errors: list[str] = []
    if plan.schema_version != "platform_postgres_orchestration_plan.v1":
        errors.append("schema_version_invalid")
    if plan.requirement != "S133":
        errors.append("requirement_invalid")
    if plan.profile != "test":
        errors.append("profile_must_be_test")
    if plan.service_order != POSTGRES_SERVICE_ORDER:
        errors.append("service_order_invalid")
    if plan.phase_order != POSTGRES_ORCHESTRATION_PHASES:
        errors.append("phase_order_invalid")
    if plan.pool_workloads != POOL_WORKLOADS:
        errors.append("pool_workloads_invalid")
    if plan.restart_count != 1:
        errors.append("restart_count_must_be_one")
    if plan.production_database_allowed:
        errors.append("production_database_must_be_forbidden")
    if plan.remote_provider_required:
        errors.append("remote_provider_must_not_be_required")
    if errors:
        raise PostgresOrchestrationEvidenceError("; ".join(errors))


def build_postgres_phase_evidence(
    *,
    service_id: str,
    phase: str,
    status: str,
    restart_iteration: int = 0,
    evidence_codes: Iterable[str] = (),
    duration_ms: int = 0,
    failure_code: str | None = None,
) -> PostgresPhaseEvidence:
    record = PostgresPhaseEvidence(
        service_id=service_id,
        phase=phase,
        status=status,
        restart_iteration=restart_iteration,
        evidence_codes=tuple(evidence_codes),
        duration_ms=duration_ms,
        failure_code=failure_code,
    )
    _validate_phase_evidence(record)
    return record


def build_platform_postgres_restart_evidence(
    *,
    run_id: str,
    state: str,
    records: Iterable[PostgresPhaseEvidence],
) -> PlatformPostgresRestartEvidence:
    evidence = PlatformPostgresRestartEvidence(
        run_id=run_id,
        state=state,
        records=tuple(records),
    )
    validate_platform_postgres_restart_evidence(evidence)
    return evidence


def validate_platform_postgres_restart_evidence(
    evidence: PlatformPostgresRestartEvidence,
) -> None:
    if not _is_safe_token(evidence.run_id):
        raise PostgresOrchestrationEvidenceError("run_id_invalid")
    if evidence.state not in POSTGRES_RUN_STATES:
        raise PostgresOrchestrationEvidenceError("run_state_invalid")
    if not evidence.records:
        raise PostgresOrchestrationEvidenceError("records_must_not_be_empty")

    seen: set[tuple[str, str, int]] = set()
    for record in evidence.records:
        _validate_phase_evidence(record)
        identity = (record.service_id, record.phase, record.restart_iteration)
        if identity in seen:
            raise PostgresOrchestrationEvidenceError("duplicate_phase_evidence")
        seen.add(identity)

    failed = any(record.status == "FAILED" for record in evidence.records)
    incomplete = any(
        record.status in {"PENDING", "RUNNING"} for record in evidence.records
    )
    if evidence.state == "FAILED" and not failed:
        raise PostgresOrchestrationEvidenceError("failed_state_requires_failure")
    if evidence.state == "PASSED" and (failed or incomplete):
        raise PostgresOrchestrationEvidenceError("passed_state_requires_completion")


def _validate_phase_evidence(record: PostgresPhaseEvidence) -> None:
    if record.service_id not in POSTGRES_SERVICE_ORDER:
        raise PostgresOrchestrationEvidenceError("service_id_invalid")
    if record.phase not in POSTGRES_ORCHESTRATION_PHASES:
        raise PostgresOrchestrationEvidenceError("phase_invalid")
    if record.status not in POSTGRES_EVIDENCE_STATUSES:
        raise PostgresOrchestrationEvidenceError("status_invalid")
    if record.restart_iteration not in {0, 1}:
        raise PostgresOrchestrationEvidenceError("restart_iteration_invalid")
    if record.duration_ms < 0:
        raise PostgresOrchestrationEvidenceError("duration_ms_invalid")
    if len(set(record.evidence_codes)) != len(record.evidence_codes):
        raise PostgresOrchestrationEvidenceError("evidence_codes_duplicate")
    if any(not _is_safe_token(code) for code in record.evidence_codes):
        raise PostgresOrchestrationEvidenceError("evidence_code_invalid")
    if record.status == "PASSED" and not record.evidence_codes:
        raise PostgresOrchestrationEvidenceError("passed_evidence_required")
    if record.status == "FAILED":
        if not record.failure_code or not _is_safe_token(record.failure_code):
            raise PostgresOrchestrationEvidenceError("failure_code_required")
    elif record.failure_code is not None:
        raise PostgresOrchestrationEvidenceError("failure_code_forbidden")


def _is_safe_token(value: str) -> bool:
    return bool(_SAFE_TOKEN.fullmatch(value))
