from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION = "ag_audit_retention_policy.v1"
AG_AUDIT_RETENTION_POLICY_ID = "ag-audit-retention-v1"
AG_AUDIT_RETENTION_RECEIPT_TABLE = "ag_ret_archives"
MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650
MIN_ARCHIVE_GRACE_DAYS = 1
MAX_ARCHIVE_GRACE_DAYS = 365
MAX_RETENTION_BATCH_SIZE = 500
ALLOWED_ARCHIVE_PROVIDER_MODES = frozenset({"mock", "external"})


@dataclass(frozen=True)
class AgAuditRetentionPolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_ag_audit_retention_policy(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    event_days = _bounded_int_env(
        env,
        "NEX_AG_AUDIT_EVENT_RETENTION_DAYS",
        365,
        minimum=MIN_RETENTION_DAYS,
        maximum=MAX_RETENTION_DAYS,
    )
    export_days = _bounded_int_env(
        env,
        "NEX_AG_EVIDENCE_EXPORT_RETENTION_DAYS",
        365,
        minimum=MIN_RETENTION_DAYS,
        maximum=MAX_RETENTION_DAYS,
    )
    grace_days = _bounded_int_env(
        env,
        "NEX_AG_ARCHIVE_GRACE_DAYS",
        30,
        minimum=MIN_ARCHIVE_GRACE_DAYS,
        maximum=MAX_ARCHIVE_GRACE_DAYS,
    )
    batch_size = _bounded_int_env(
        env,
        "NEX_AG_RETENTION_BATCH_SIZE",
        100,
        minimum=1,
        maximum=MAX_RETENTION_BATCH_SIZE,
    )
    provider_mode = _choice_env(
        env,
        "NEX_AG_ARCHIVE_PROVIDER_MODE",
        "mock",
        ALLOWED_ARCHIVE_PROVIDER_MODES,
    )
    execute_enabled = _bool_env(
        env,
        "NEX_AG_RETENTION_EXECUTE_ENABLED",
        False,
    )
    if grace_days > min(event_days, export_days):
        raise AgAuditRetentionPolicyError(
            error_code="ag.retention.archive_grace_exceeds_retention",
            detail=(
                "Archive grace days cannot exceed the shortest source "
                "retention period."
            ),
        )
    if execute_enabled and provider_mode != "external":
        raise AgAuditRetentionPolicyError(
            error_code="ag.retention.execute_requires_external_archive",
            detail=(
                "Physical purge enablement requires the external archive "
                "provider mode."
            ),
        )
    return {
        "policy_schema_version": AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION,
        "policy_id": AG_AUDIT_RETENTION_POLICY_ID,
        "service_id": "nex-ag",
        "sources": [
            {
                "source_kind": "operational_event",
                "table_name": "service_operational_events",
                "identity_field": "event_id",
                "timestamp_field": "created_at",
                "retention_days": event_days,
            },
            {
                "source_kind": "evidence_export",
                "table_name": "ag_ev_exports",
                "identity_field": "export_id",
                "timestamp_field": "updated_at",
                "retention_days": export_days,
            },
        ],
        "archive": {
            "provider_mode": provider_mode,
            "recoverable_payload_required": True,
            "sealed_receipt_required": True,
            "receipt_table": AG_AUDIT_RETENTION_RECEIPT_TABLE,
            "digest_algorithm": "sha256",
            "grace_days": grace_days,
            "raw_payload_in_receipt": False,
        },
        "purge": {
            "dry_run_default": True,
            "execute_enabled": execute_enabled,
            "explicit_confirmation_required": True,
            "same_transaction_recheck_required": True,
            "batch_size": batch_size,
            "hard_max_batch_size": MAX_RETENTION_BATCH_SIZE,
        },
    }


def _bounded_int_env(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise AgAuditRetentionPolicyError(
            error_code="ag.retention.policy_value_invalid",
            detail=f"{name} must be an integer.",
        ) from exc
    if isinstance(raw, bool) or value < minimum or value > maximum:
        raise AgAuditRetentionPolicyError(
            error_code="ag.retention.policy_value_out_of_range",
            detail=f"{name} must be between {minimum} and {maximum}.",
        )
    return value


def _choice_env(
    environ: Mapping[str, str],
    name: str,
    default: str,
    choices: frozenset[str],
) -> str:
    value = str(environ.get(name) or default).strip().lower()
    if value not in choices:
        raise AgAuditRetentionPolicyError(
            error_code="ag.retention.archive_provider_mode_invalid",
            detail=f"{name} must be one of: {', '.join(sorted(choices))}.",
        )
    return value


def _bool_env(
    environ: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    normalized = str(raw).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise AgAuditRetentionPolicyError(
        error_code="ag.retention.policy_boolean_invalid",
        detail=f"{name} must be a boolean value.",
    )
