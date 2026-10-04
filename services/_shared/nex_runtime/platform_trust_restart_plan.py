from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


PLATFORM_TRUST_RESTART_PLAN_SCHEMA_VERSION = "platform_trust_restart_plan.v1"
TRUST_PROCESS_START_ORDER = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
TRUST_PROCESS_STOP_ORDER = tuple(reversed(TRUST_PROCESS_START_ORDER))
TRUST_RESTART_PHASES = (
    "MIGRATE",
    "SEED_AUTHORITY",
    "START_GENERATION_1",
    "EXCHANGE_GRANTS",
    "LOGIN_USER",
    "VERIFY_CHAIN",
    "VERIFY_DENIALS",
    "STOP_GENERATION_1",
    "START_GENERATION_2",
    "VERIFY_RESTORED_SESSION",
    "VERIFY_RESTORED_JWKS",
    "REVOKE_SERVICE_TOKEN",
    "VERIFY_REVOKED_TOKEN_DENIED",
    "STOP_GENERATION_2",
    "CLEANUP",
    "VERIFY_CLEAN",
)
TRUST_RESTART_CHECKPOINTS = (
    "jwks_restored",
    "user_session_restored",
    "revocation_persisted",
    "revoked_token_denied",
)


@dataclass(frozen=True)
class PlatformTrustRestartPlan:
    phase_order: tuple[str, ...]
    process_start_order: tuple[str, ...]
    process_stop_order: tuple[str, ...]
    generation_count: int
    database_service_count: int
    remote_model_providers_allowed: bool
    temporary_key_cleanup_required: bool

    def to_wire(self) -> dict[str, Any]:
        return asdict(self)


def build_platform_trust_restart_plan() -> PlatformTrustRestartPlan:
    return PlatformTrustRestartPlan(
        phase_order=TRUST_RESTART_PHASES,
        process_start_order=TRUST_PROCESS_START_ORDER,
        process_stop_order=TRUST_PROCESS_STOP_ORDER,
        generation_count=2,
        database_service_count=5,
        remote_model_providers_allowed=False,
        temporary_key_cleanup_required=True,
    )


def validate_platform_trust_restart_plan(
    plan: PlatformTrustRestartPlan,
) -> tuple[str, ...]:
    issues: list[str] = []
    if plan.phase_order != TRUST_RESTART_PHASES:
        issues.append("phase_order_invalid")
    if plan.process_start_order != TRUST_PROCESS_START_ORDER:
        issues.append("process_start_order_invalid")
    if plan.process_stop_order != tuple(reversed(plan.process_start_order)):
        issues.append("process_stop_order_invalid")
    if plan.generation_count != 2:
        issues.append("generation_count_invalid")
    if plan.database_service_count != 5:
        issues.append("database_service_count_invalid")
    if plan.remote_model_providers_allowed:
        issues.append("remote_model_provider_boundary_invalid")
    if not plan.temporary_key_cleanup_required:
        issues.append("temporary_key_cleanup_missing")
    return tuple(issues)


def evaluate_platform_trust_restart_checkpoints(
    checkpoints: Sequence[str],
) -> dict[str, Any]:
    observed = tuple(checkpoints)
    duplicate_count = len(observed) - len(set(observed))
    missing = sorted(set(TRUST_RESTART_CHECKPOINTS) - set(observed))
    unknown = sorted(set(observed) - set(TRUST_RESTART_CHECKPOINTS))
    passed = not missing and not unknown and duplicate_count == 0
    return {
        "checkpoint_schema_version": "platform_trust_restart_checkpoints.v1",
        "status": "PASS" if passed else "FAIL",
        "checkpoint_count": len(observed),
        "missing_checkpoints": missing,
        "unknown_checkpoints": unknown,
        "duplicate_count": duplicate_count,
    }
