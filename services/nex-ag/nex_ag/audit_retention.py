from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker


AG_AUDIT_RETENTION_POLICY_SCHEMA_VERSION = "ag_audit_retention_policy.v1"
AG_AUDIT_RETENTION_POLICY_ID = "ag-audit-retention-v1"
AG_AUDIT_RETENTION_RECEIPT_TABLE = "ag_ret_archives"
MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650
MIN_ARCHIVE_GRACE_DAYS = 1
MAX_ARCHIVE_GRACE_DAYS = 365
MAX_RETENTION_BATCH_SIZE = 500
ALLOWED_ARCHIVE_PROVIDER_MODES = frozenset({"mock", "external"})
AG_RETENTION_CANDIDATE_PAGE_SCHEMA_VERSION = "ag_retention_candidate_page.v1"
AG_RETENTION_CANDIDATE_SCHEMA_VERSION = "ag_retention_candidate.v1"


@dataclass(frozen=True)
class AgAuditRetentionPolicyError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgRetentionCandidateError(RuntimeError):
    error_code: str
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail


class InMemoryAgRetentionCandidateStore:
    def __init__(
        self,
        *,
        event_records: Sequence[Mapping[str, Any]] | None = None,
        export_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.event_records = list(event_records or [])
        self.export_records = list(export_records or [])

    def list_candidates(
        self,
        *,
        policy: Mapping[str, Any],
        as_of: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return build_ag_retention_candidate_page(
            event_records=self.event_records,
            export_records=self.export_records,
            policy=policy,
            as_of=as_of,
            limit=limit,
        )


class SqlAlchemyAgRetentionCandidateStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_candidates(
        self,
        *,
        policy: Mapping[str, Any],
        as_of: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        normalized_as_of = _parse_timestamp(as_of, field="as_of")
        normalized_limit = _normalize_candidate_limit(policy, limit)
        source_policies = _source_policy_map(policy)
        event_cutoff = normalized_as_of - timedelta(
            days=source_policies["operational_event"]["retention_days"]
        )
        export_cutoff = normalized_as_of - timedelta(
            days=source_policies["evidence_export"]["retention_days"]
        )
        query_limit = normalized_limit + 1
        try:
            with self._session_factory() as session:
                event_rows = session.execute(
                    text(
                        """
                        SELECT event_id, service_id, event_type, severity,
                               trace_id, request_id, subject_type, subject_id,
                               message, details, created_at
                        FROM service_operational_events
                        WHERE created_at <= :cutoff
                        ORDER BY created_at ASC, event_id ASC
                        LIMIT :limit
                        """
                    ),
                    {
                        "cutoff": _timestamp(event_cutoff),
                        "limit": query_limit,
                    },
                ).mappings().all()
                export_rows = session.execute(
                    text(
                        """
                        SELECT export_id, export_schema_version, target_service,
                               target_kind, target_id, trace_id, request_id,
                               operator_type, operator_id, tenant_id,
                               operator_ref, export_status, export_format,
                               redaction_profile, evidence_manifest,
                               evidence_hash, evidence_item_count, metadata,
                               created_at, updated_at
                        FROM ag_ev_exports
                        WHERE updated_at <= :cutoff
                        ORDER BY updated_at ASC, export_id ASC
                        LIMIT :limit
                        """
                    ),
                    {
                        "cutoff": _timestamp(export_cutoff),
                        "limit": query_limit,
                    },
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise AgRetentionCandidateError(
                error_code="ag.retention.candidate_store_unavailable",
                detail="AG retention candidate source is unavailable.",
                status_code=503,
            ) from exc
        return build_ag_retention_candidate_page(
            event_records=event_rows,
            export_records=export_rows,
            policy=policy,
            as_of=as_of,
            limit=normalized_limit,
        )


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


def build_ag_retention_candidate_page(
    *,
    event_records: Sequence[Mapping[str, Any]],
    export_records: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    as_of: str,
    limit: int | None = None,
) -> dict[str, Any]:
    normalized_as_of = _parse_timestamp(as_of, field="as_of")
    normalized_limit = _normalize_candidate_limit(policy, limit)
    source_policies = _source_policy_map(policy)
    candidates: list[dict[str, Any]] = []
    invalid_record_count = 0
    for source_kind, records in (
        ("operational_event", event_records),
        ("evidence_export", export_records),
    ):
        source_policy = source_policies[source_kind]
        cutoff = normalized_as_of - timedelta(
            days=source_policy["retention_days"]
        )
        for record in records:
            candidate = _candidate_from_record(
                record,
                source_policy=source_policy,
                cutoff=cutoff,
            )
            if candidate is None:
                invalid_record_count += 1
            elif _parse_timestamp(
                candidate["source_timestamp"], field="source_timestamp"
            ) <= cutoff:
                candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            item["source_timestamp"],
            item["source_kind"],
            item["source_id"],
        )
    )
    selected = candidates[:normalized_limit]
    return {
        "candidate_page_schema_version": (
            AG_RETENTION_CANDIDATE_PAGE_SCHEMA_VERSION
        ),
        "policy_id": str(policy.get("policy_id") or ""),
        "as_of": _timestamp(normalized_as_of),
        "limit": normalized_limit,
        "candidate_count": len(selected),
        "eligible_count": len(candidates),
        "invalid_record_count": invalid_record_count,
        "has_more": len(candidates) > normalized_limit,
        "items": selected,
        "raw_payload_included": False,
    }


def _candidate_from_record(
    record: Mapping[str, Any],
    *,
    source_policy: Mapping[str, Any],
    cutoff: datetime,
) -> dict[str, Any] | None:
    source_id = record.get(source_policy["identity_field"])
    source_timestamp = record.get(source_policy["timestamp_field"])
    if not isinstance(source_id, str) or not source_id.strip():
        return None
    try:
        parsed_timestamp = _parse_timestamp(
            source_timestamp,
            field=str(source_policy["timestamp_field"]),
        )
    except AgRetentionCandidateError:
        return None
    source_kind = str(source_policy["source_kind"])
    normalized_id = source_id.strip()
    return {
        "candidate_schema_version": AG_RETENTION_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": _sha256_text(f"{source_kind}:{normalized_id}"),
        "source_kind": source_kind,
        "source_id": normalized_id,
        "source_timestamp": _timestamp(parsed_timestamp),
        "retention_days": int(source_policy["retention_days"]),
        "retention_cutoff": _timestamp(cutoff),
        "content_sha256": _sha256_json(record),
        "archive_required": True,
        "archive_status": "UNARCHIVED",
        "purge_eligible": False,
        "raw_payload_included": False,
    }


def _source_policy_map(
    policy: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    sources = policy.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        raise AgRetentionCandidateError(
            error_code="ag.retention.policy_sources_invalid",
            detail="AG retention policy sources are invalid.",
        )
    mapped = {
        str(item.get("source_kind")): item
        for item in sources
        if isinstance(item, Mapping)
    }
    if set(mapped) != {"operational_event", "evidence_export"}:
        raise AgRetentionCandidateError(
            error_code="ag.retention.policy_sources_invalid",
            detail="AG retention policy must define both source kinds.",
        )
    return mapped


def _normalize_candidate_limit(
    policy: Mapping[str, Any],
    limit: int | None,
) -> int:
    purge = policy.get("purge")
    if not isinstance(purge, Mapping):
        raise AgRetentionCandidateError(
            error_code="ag.retention.policy_purge_invalid",
            detail="AG retention purge policy is invalid.",
        )
    policy_limit = purge.get("batch_size")
    hard_limit = purge.get("hard_max_batch_size")
    if (
        isinstance(policy_limit, bool)
        or not isinstance(policy_limit, int)
        or isinstance(hard_limit, bool)
        or not isinstance(hard_limit, int)
        or policy_limit < 1
        or hard_limit < 1
        or policy_limit > hard_limit
    ):
        raise AgRetentionCandidateError(
            error_code="ag.retention.policy_batch_invalid",
            detail="AG retention batch policy is invalid.",
        )
    value = policy_limit if limit is None else limit
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AgRetentionCandidateError(
            error_code="ag.retention.candidate_limit_invalid",
            detail="Candidate limit must be a positive integer.",
        )
    if value > hard_limit:
        raise AgRetentionCandidateError(
            error_code="ag.retention.candidate_limit_exceeded",
            detail=f"Candidate limit cannot exceed {hard_limit}.",
        )
    return value


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgRetentionCandidateError(
                error_code="ag.retention.timestamp_invalid",
                detail=f"{field} must be an ISO-8601 timestamp.",
            ) from exc
    else:
        raise AgRetentionCandidateError(
            error_code="ag.retention.timestamp_invalid",
            detail=f"{field} must be an ISO-8601 timestamp.",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgRetentionCandidateError(
            error_code="ag.retention.timestamp_timezone_required",
            detail=f"{field} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_json(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return _timestamp(value)
    return value


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


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
