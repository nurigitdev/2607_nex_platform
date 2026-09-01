from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.artifacts import (
    ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS,
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
    ArtifactHandoffError,
    assert_artifact_retention_payload_safe,
    build_artifact_retention_scheduler_config,
    format_artifact_retention_timestamp,
    optional_text,
    parse_artifact_retention_timestamp,
    sha256_json,
    validate_artifact_retention_scheduler_config,
)


AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_request.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_record.v1"
)
AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION = (
    "ae_artifact_retention_scheduler_lease_decision.v1"
)

DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID = (
    "ae-artifact-retention-scheduler-manual-once"
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE = "manual_tick_once"
ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATIONS = (
    ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE,
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_STATUSES = (
    "HELD",
    "RELEASED",
    "EXPIRED",
)
ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_STATUSES = (
    "ACQUIRED",
    "BUSY",
)
MIN_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS = 60
MAX_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS = (
    ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS
)


def build_artifact_retention_scheduler_lease_request(
    *,
    scheduler_config: Mapping[str, Any] | None = None,
    scheduler_id: str | None = None,
    lease_owner_id: str = DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_OWNER_ID,
    requested_at: str | None = None,
    lease_ttl_seconds: int | str | None = None,
    operation: str = ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATION_MANUAL_TICK_ONCE,
    tick_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    config = validate_artifact_retention_scheduler_config(
        dict(scheduler_config)
        if scheduler_config is not None
        else build_artifact_retention_scheduler_config()
    )
    normalized_scheduler_id = _required_text(
        scheduler_id or config["scheduler_id"],
        "scheduler_id",
        "ae.artifact_retention_scheduler_lease_request_invalid",
    )
    normalized_owner_id = _required_text(
        lease_owner_id,
        "lease_owner_id",
        "ae.artifact_retention_scheduler_lease_request_invalid",
    )
    ttl_seconds = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        lease_ttl_seconds
    )
    requested_dt = parse_artifact_retention_timestamp(
        requested_at or _request_time_from_config(config),
        field_name="requested_at",
    )
    normalized_requested_at = format_artifact_retention_timestamp(requested_dt)
    expires_at = format_artifact_retention_timestamp(
        requested_dt + timedelta(seconds=ttl_seconds)
    )
    normalized_operation = normalize_artifact_retention_scheduler_lease_operation(
        operation
    )
    normalized_idempotency_key = optional_text(
        idempotency_key
    ) or artifact_retention_scheduler_lease_idempotency_key(
        scheduler_id=normalized_scheduler_id,
        lease_owner_id=normalized_owner_id,
        operation=normalized_operation,
        requested_at=normalized_requested_at,
    )
    request = {
        "lease_request_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": normalized_scheduler_id,
        "lease_owner_id": normalized_owner_id,
        "operation": normalized_operation,
        "tick_id": optional_text(tick_id),
        "requested_at": normalized_requested_at,
        "expires_at": expires_at,
        "lease_ttl_seconds": ttl_seconds,
        "stale_after_seconds": ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS,
        "idempotency_key": normalized_idempotency_key,
        "guardrails": {
            "lease_required_before_tick": True,
            "manual_once_runner": True,
            "daemon_auto_start_allowed": False,
            "scheduler_daemon_started": False,
            "continuous_loop_started": False,
            "continuous_loop_allowed_before_lease": False,
            "physical_delete_automation_enabled": False,
        },
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_request(request)


def validate_artifact_retention_scheduler_lease_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request must be an object.",
        )
    normalized = dict(request)
    if (
        normalized.get("lease_request_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_REQUEST_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_schema_invalid",
            detail="Artifact retention scheduler lease request schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request service id is invalid.",
        )
    for field_name in ("scheduler_id", "lease_owner_id", "idempotency_key"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_request_invalid",
        )
    operation = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    ttl_seconds = normalize_artifact_retention_scheduler_lease_ttl_seconds(
        normalized.get("lease_ttl_seconds")
    )
    requested_at = parse_artifact_retention_timestamp(
        normalized.get("requested_at"),
        field_name="requested_at",
    )
    expires_at = parse_artifact_retention_timestamp(
        normalized.get("expires_at"),
        field_name="expires_at",
    )
    expected_expires_at = format_artifact_retention_timestamp(
        requested_at + timedelta(seconds=ttl_seconds)
    )
    if format_artifact_retention_timestamp(expires_at) != expected_expires_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request expires_at is invalid.",
        )
    if normalized.get("stale_after_seconds") != (
        ARTIFACT_RETENTION_SCHEDULER_TICK_STALE_AFTER_SECONDS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease stale window is invalid.",
        )
    if optional_text(normalized.get("tick_id")) != normalized.get("tick_id"):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease tick id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_request_invalid",
            detail="Artifact retention scheduler lease request metadata is invalid.",
        )
    normalized["operation"] = operation
    normalized["lease_ttl_seconds"] = ttl_seconds
    normalized["requested_at"] = format_artifact_retention_timestamp(requested_at)
    normalized["expires_at"] = expected_expires_at
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def build_artifact_retention_scheduler_lease_record(
    request: Mapping[str, Any],
    *,
    lease_token: str | None = None,
    fencing_token: int | str = 1,
    lease_status: str = "HELD",
    acquired_at: str | None = None,
    expires_at: str | None = None,
    released_at: str | None = None,
    last_observed_at: str | None = None,
) -> dict[str, Any]:
    validated_request = validate_artifact_retention_scheduler_lease_request(request)
    normalized_fencing_token = _positive_int(
        fencing_token,
        "fencing_token",
        "ae.artifact_retention_scheduler_lease_record_invalid",
    )
    normalized_status = normalize_artifact_retention_scheduler_lease_record_status(
        lease_status
    )
    normalized_acquired_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            acquired_at or validated_request["requested_at"],
            field_name="acquired_at",
        )
    )
    normalized_expires_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            expires_at or validated_request["expires_at"],
            field_name="expires_at",
        )
    )
    normalized_released_at = (
        format_artifact_retention_timestamp(
            parse_artifact_retention_timestamp(released_at, field_name="released_at")
        )
        if released_at is not None
        else None
    )
    normalized_last_observed_at = format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(
            last_observed_at or normalized_acquired_at,
            field_name="last_observed_at",
        )
    )
    normalized_lease_token = optional_text(lease_token) or _lease_token(
        validated_request,
        fencing_token=normalized_fencing_token,
    )
    record = {
        "lease_record_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
        ),
        "lease_record_id": _lease_record_id(
            scheduler_id=validated_request["scheduler_id"],
            lease_token=normalized_lease_token,
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_request["scheduler_id"],
        "lease_owner_id": validated_request["lease_owner_id"],
        "lease_token": normalized_lease_token,
        "lease_status": normalized_status,
        "fencing_token": normalized_fencing_token,
        "acquired_at": normalized_acquired_at,
        "expires_at": normalized_expires_at,
        "released_at": normalized_released_at,
        "last_observed_at": normalized_last_observed_at,
        "operation": validated_request["operation"],
        "tick_id": validated_request["tick_id"],
        "idempotency_key": validated_request["idempotency_key"],
        "guardrails": deepcopy(validated_request["guardrails"]),
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_record(record)


def validate_artifact_retention_scheduler_lease_record(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record must be an object.",
        )
    normalized = dict(record)
    if (
        normalized.get("lease_record_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_schema_invalid",
            detail="Artifact retention scheduler lease record schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record service id is invalid.",
        )
    for field_name in (
        "lease_record_id",
        "scheduler_id",
        "lease_owner_id",
        "lease_token",
        "idempotency_key",
    ):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_record_invalid",
        )
    normalized["operation"] = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    normalized["lease_status"] = normalize_artifact_retention_scheduler_lease_record_status(
        normalized.get("lease_status")
    )
    normalized["fencing_token"] = _positive_int(
        normalized.get("fencing_token"),
        "fencing_token",
        "ae.artifact_retention_scheduler_lease_record_invalid",
    )
    acquired_at = parse_artifact_retention_timestamp(
        normalized.get("acquired_at"),
        field_name="acquired_at",
    )
    expires_at = parse_artifact_retention_timestamp(
        normalized.get("expires_at"),
        field_name="expires_at",
    )
    last_observed_at = parse_artifact_retention_timestamp(
        normalized.get("last_observed_at"),
        field_name="last_observed_at",
    )
    if expires_at <= acquired_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease expiry must follow acquisition.",
        )
    released_at = normalized.get("released_at")
    if normalized["lease_status"] == "RELEASED":
        if released_at is None:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_record_invalid",
                detail="Released artifact retention scheduler lease requires released_at.",
            )
        released_dt = parse_artifact_retention_timestamp(
            released_at,
            field_name="released_at",
        )
        if released_dt < acquired_at:
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_record_invalid",
                detail="Artifact retention scheduler lease release precedes acquisition.",
            )
    elif released_at is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Only released scheduler leases may carry released_at.",
        )
    if last_observed_at < acquired_at:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease observation precedes acquisition.",
        )
    if optional_text(normalized.get("tick_id")) != normalized.get("tick_id"):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease tick id is invalid.",
        )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_invalid",
            detail="Artifact retention scheduler lease record metadata is invalid.",
        )
    normalized["acquired_at"] = format_artifact_retention_timestamp(acquired_at)
    normalized["expires_at"] = format_artifact_retention_timestamp(expires_at)
    normalized["last_observed_at"] = format_artifact_retention_timestamp(
        last_observed_at
    )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def release_artifact_retention_scheduler_lease(
    record: Mapping[str, Any],
    *,
    lease_token: str,
    released_at: str | None = None,
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_lease_record(record)
    normalized_token = _required_text(
        lease_token,
        "lease_token",
        "ae.artifact_retention_scheduler_lease_release_invalid",
    )
    if normalized_token != validated["lease_token"]:
        raise ArtifactHandoffError(
            status_code=409,
            error_code="ae.artifact_retention_scheduler_lease_token_mismatch",
            detail="Artifact retention scheduler lease token does not match.",
        )
    if validated["lease_status"] == "RELEASED":
        return validated
    released = {
        **validated,
        "lease_status": "RELEASED",
        "released_at": (
            released_at
            or format_artifact_retention_timestamp(
                parse_artifact_retention_timestamp(
                    validated["last_observed_at"],
                    field_name="released_at",
                )
            )
        ),
        "last_observed_at": released_at or validated["last_observed_at"],
    }
    return validate_artifact_retention_scheduler_lease_record(released)


def build_artifact_retention_scheduler_lease_decision(
    request: Mapping[str, Any],
    *,
    lease_record: Mapping[str, Any] | None = None,
    blocking_lease: Mapping[str, Any] | None = None,
    decision_at: str | None = None,
) -> dict[str, Any]:
    validated_request = validate_artifact_retention_scheduler_lease_request(request)
    acquired_record = (
        validate_artifact_retention_scheduler_lease_record(lease_record)
        if lease_record is not None
        else None
    )
    blocked_record = (
        validate_artifact_retention_scheduler_lease_record(blocking_lease)
        if blocking_lease is not None
        else None
    )
    if acquired_record is not None and blocked_record is not None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Lease decision cannot be both acquired and busy.",
        )
    decision_status = "ACQUIRED" if acquired_record is not None else "BUSY"
    if decision_status == "BUSY" and blocked_record is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Busy scheduler lease decision requires a blocking lease.",
        )
    decision = {
        "lease_decision_schema_version": (
            AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION
        ),
        "service_id": "nex-ae-api",
        "scheduler_id": validated_request["scheduler_id"],
        "lease_owner_id": validated_request["lease_owner_id"],
        "operation": validated_request["operation"],
        "decision_status": decision_status,
        "lease_acquired": decision_status == "ACQUIRED",
        "skip_reason": None if decision_status == "ACQUIRED" else "lease_busy",
        "decision_at": format_artifact_retention_timestamp(
            parse_artifact_retention_timestamp(
                decision_at or validated_request["requested_at"],
                field_name="decision_at",
            )
        ),
        "lease_record": deepcopy(acquired_record),
        "blocking_lease": deepcopy(blocked_record),
        "lease_token": acquired_record["lease_token"] if acquired_record else None,
        "fencing_token": acquired_record["fencing_token"] if acquired_record else None,
        "idempotency_key": validated_request["idempotency_key"],
        "guardrails": deepcopy(validated_request["guardrails"]),
        "metadata": _scheduler_lease_metadata(),
    }
    return validate_artifact_retention_scheduler_lease_decision(decision)


def validate_artifact_retention_scheduler_lease_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(decision, Mapping):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision must be an object.",
        )
    normalized = dict(decision)
    if (
        normalized.get("lease_decision_schema_version")
        != AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_SCHEMA_VERSION
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_schema_invalid",
            detail="Artifact retention scheduler lease decision schema version is invalid.",
        )
    if normalized.get("service_id") != "nex-ae-api":
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision service id is invalid.",
        )
    for field_name in ("scheduler_id", "lease_owner_id", "operation", "idempotency_key"):
        _required_text(
            normalized.get(field_name),
            field_name,
            "ae.artifact_retention_scheduler_lease_decision_invalid",
        )
    normalized["operation"] = normalize_artifact_retention_scheduler_lease_operation(
        normalized.get("operation")
    )
    parse_artifact_retention_timestamp(
        normalized.get("decision_at"),
        field_name="decision_at",
    )
    decision_status = normalized.get("decision_status")
    if decision_status not in ARTIFACT_RETENTION_SCHEDULER_LEASE_DECISION_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision status is invalid.",
        )
    if decision_status == "ACQUIRED":
        lease_record = validate_artifact_retention_scheduler_lease_record(
            normalized.get("lease_record")
        )
        if (
            normalized.get("lease_acquired") is not True
            or normalized.get("skip_reason") is not None
            or normalized.get("blocking_lease") is not None
            or normalized.get("lease_token") != lease_record["lease_token"]
            or normalized.get("fencing_token") != lease_record["fencing_token"]
            or lease_record["scheduler_id"] != normalized["scheduler_id"]
            or lease_record["lease_owner_id"] != normalized["lease_owner_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
                detail="Acquired artifact retention scheduler lease decision is invalid.",
            )
    else:
        blocking_lease = validate_artifact_retention_scheduler_lease_record(
            normalized.get("blocking_lease")
        )
        if (
            normalized.get("lease_acquired") is not False
            or normalized.get("skip_reason") != "lease_busy"
            or normalized.get("lease_record") is not None
            or normalized.get("lease_token") is not None
            or normalized.get("fencing_token") is not None
            or blocking_lease["scheduler_id"] != normalized["scheduler_id"]
        ):
            raise ArtifactHandoffError(
                status_code=422,
                error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
                detail="Busy artifact retention scheduler lease decision is invalid.",
            )
    if normalized.get("guardrails") != _scheduler_lease_guardrails():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision guardrails are invalid.",
        )
    if normalized.get("metadata") != _scheduler_lease_metadata():
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_decision_invalid",
            detail="Artifact retention scheduler lease decision metadata is invalid.",
        )
    assert_artifact_retention_payload_safe(normalized)
    return normalized


def summarize_artifact_retention_scheduler_lease_decision(
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    validated = validate_artifact_retention_scheduler_lease_decision(decision)
    return {
        "scheduler_id": validated["scheduler_id"],
        "decision_status": validated["decision_status"],
        "lease_acquired": validated["lease_acquired"],
        "lease_owner_id": validated["lease_owner_id"],
        "operation": validated["operation"],
        "fencing_token": validated["fencing_token"],
        "skip_reason": validated["skip_reason"],
    }


@dataclass
class ArtifactRetentionSchedulerLeaseStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ensure_available(self) -> None:
        return None

    def get(self, scheduler_id: str) -> dict[str, Any] | None:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        record = self.records.get(normalized_scheduler_id)
        return deepcopy(record) if record is not None else None

    def acquire(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validated_request = validate_artifact_retention_scheduler_lease_request(request)
        current = self.records.get(validated_request["scheduler_id"])
        if current is not None and _lease_matches_request(current, validated_request):
            return build_artifact_retention_scheduler_lease_decision(
                validated_request,
                lease_record=current,
            )
        if current is not None and _lease_blocks_acquisition(
            current,
            requested_at=validated_request["requested_at"],
        ):
            return build_artifact_retention_scheduler_lease_decision(
                validated_request,
                blocking_lease=current,
            )
        record = build_artifact_retention_scheduler_lease_record(
            validated_request,
            fencing_token=_next_fencing_token(current),
            acquired_at=validated_request["requested_at"],
            last_observed_at=validated_request["requested_at"],
        )
        self.records[validated_request["scheduler_id"]] = deepcopy(record)
        return build_artifact_retention_scheduler_lease_decision(
            validated_request,
            lease_record=record,
        )

    def release(
        self,
        *,
        scheduler_id: str,
        lease_token: str,
        released_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        current = self.records.get(normalized_scheduler_id)
        if current is None:
            raise ArtifactHandoffError(
                status_code=404,
                error_code="ae.artifact_retention_scheduler_lease_not_found",
                detail="Artifact retention scheduler lease was not found.",
            )
        released = release_artifact_retention_scheduler_lease(
            current,
            lease_token=lease_token,
            released_at=released_at,
        )
        self.records[normalized_scheduler_id] = deepcopy(released)
        return released


class SqlAlchemyArtifactRetentionSchedulerLeaseStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_available(self) -> None:
        try:
            with self._session_factory() as session:
                session.execute(
                    text("SELECT 1 FROM ae_artifact_retention_scheduler_leases LIMIT 1")
                )
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def get(self, scheduler_id: str) -> dict[str, Any] | None:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        try:
            with self._session_factory() as session:
                return _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                )
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def acquire(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validated_request = validate_artifact_retention_scheduler_lease_request(request)
        try:
            with self._session_factory() as session:
                current = _select_scheduler_lease(
                    session,
                    scheduler_id=validated_request["scheduler_id"],
                    for_update=True,
                )
                if current is not None and _lease_matches_request(
                    current,
                    validated_request,
                ):
                    session.commit()
                    return build_artifact_retention_scheduler_lease_decision(
                        validated_request,
                        lease_record=current,
                    )
                if current is not None and _lease_blocks_acquisition(
                    current,
                    requested_at=validated_request["requested_at"],
                ):
                    session.commit()
                    return build_artifact_retention_scheduler_lease_decision(
                        validated_request,
                        blocking_lease=current,
                    )
                record = build_artifact_retention_scheduler_lease_record(
                    validated_request,
                    fencing_token=_next_fencing_token(current),
                    acquired_at=validated_request["requested_at"],
                    last_observed_at=validated_request["requested_at"],
                )
                _upsert_scheduler_lease(session, record)
                session.commit()
                stored = _select_scheduler_lease(
                    session,
                    scheduler_id=validated_request["scheduler_id"],
                )
                if stored is None:
                    raise ArtifactHandoffError(
                        status_code=503,
                        error_code=(
                            "ae.artifact_retention_scheduler_lease_store_unavailable"
                        ),
                        detail="AE artifact retention scheduler lease store is unavailable.",
                        retryable=True,
                    )
                return build_artifact_retention_scheduler_lease_decision(
                    validated_request,
                    lease_record=stored,
                )
        except ArtifactHandoffError:
            raise
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc

    def release(
        self,
        *,
        scheduler_id: str,
        lease_token: str,
        released_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_scheduler_id = _required_text(
            scheduler_id,
            "scheduler_id",
            "ae.artifact_retention_scheduler_lease_store_invalid",
        )
        try:
            with self._session_factory() as session:
                current = _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                    for_update=True,
                )
                if current is None:
                    raise ArtifactHandoffError(
                        status_code=404,
                        error_code="ae.artifact_retention_scheduler_lease_not_found",
                        detail="Artifact retention scheduler lease was not found.",
                    )
                released = release_artifact_retention_scheduler_lease(
                    current,
                    lease_token=lease_token,
                    released_at=released_at,
                )
                _upsert_scheduler_lease(session, released)
                session.commit()
                stored = _select_scheduler_lease(
                    session,
                    scheduler_id=normalized_scheduler_id,
                )
                return released if stored is None else stored
        except ArtifactHandoffError:
            raise
        except SQLAlchemyError as exc:
            raise _lease_store_unavailable() from exc


DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE = (
    ArtifactRetentionSchedulerLeaseStore()
)


def build_default_artifact_retention_scheduler_lease_store(app: Any) -> Any:
    persistence = getattr(app.state, "nex_persistence", None)
    session_factory = getattr(persistence, "api_session_factory", None)
    if session_factory is not None:
        return SqlAlchemyArtifactRetentionSchedulerLeaseStore(session_factory)
    return DEFAULT_ARTIFACT_RETENTION_SCHEDULER_LEASE_STORE


def artifact_retention_scheduler_lease_table_sql(dialect_name: str) -> str:
    timestamp_type = "TIMESTAMPTZ" if dialect_name == "postgresql" else "TEXT"
    json_type = "JSONB" if dialect_name == "postgresql" else "TEXT"
    json_default = "'{}'::jsonb" if dialect_name == "postgresql" else "'{}'"
    json_object_check = (
        "CHECK (jsonb_typeof({field}) = 'object')"
        if dialect_name == "postgresql"
        else ""
    )
    return f"""
        CREATE TABLE IF NOT EXISTS ae_artifact_retention_scheduler_leases (
            scheduler_id TEXT PRIMARY KEY,
            lease_record_id TEXT NOT NULL,
            lease_record_schema_version TEXT NOT NULL
                DEFAULT '{AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION}'
                CHECK (
                    lease_record_schema_version =
                    '{AE_ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_SCHEMA_VERSION}'
                ),
            service_id TEXT NOT NULL DEFAULT 'nex-ae-api'
                CHECK (service_id = 'nex-ae-api'),
            lease_owner_id TEXT NOT NULL,
            lease_token TEXT NOT NULL,
            lease_status TEXT NOT NULL
                CHECK (lease_status IN ('HELD', 'RELEASED', 'EXPIRED')),
            fencing_token INTEGER NOT NULL CHECK (fencing_token >= 1),
            acquired_at {timestamp_type} NOT NULL,
            expires_at {timestamp_type} NOT NULL,
            released_at {timestamp_type},
            last_observed_at {timestamp_type} NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN ('manual_tick_once')),
            tick_id TEXT,
            idempotency_key TEXT NOT NULL,
            guardrails {json_type} NOT NULL DEFAULT {json_default}
                {json_object_check.format(field='guardrails')},
            metadata {json_type} NOT NULL DEFAULT {json_default}
                {json_object_check.format(field='metadata')},
            updated_at {timestamp_type} NOT NULL
        )
    """


def _select_scheduler_lease(
    session: Session,
    *,
    scheduler_id: str,
    for_update: bool = False,
) -> dict[str, Any] | None:
    dialect_name = _dialect_name(session)
    lock_sql = " FOR UPDATE" if for_update and dialect_name == "postgresql" else ""
    row = (
        session.execute(
            text(
                f"""
                SELECT
                    scheduler_id,
                    lease_record_id,
                    lease_record_schema_version,
                    service_id,
                    lease_owner_id,
                    lease_token,
                    lease_status,
                    fencing_token,
                    acquired_at,
                    expires_at,
                    released_at,
                    last_observed_at,
                    operation,
                    tick_id,
                    idempotency_key,
                    guardrails,
                    metadata,
                    updated_at
                FROM ae_artifact_retention_scheduler_leases
                WHERE scheduler_id = :scheduler_id
                {lock_sql}
                """
            ),
            {"scheduler_id": scheduler_id},
        )
        .mappings()
        .first()
    )
    return _scheduler_lease_from_row(row) if row is not None else None


def _upsert_scheduler_lease(session: Session, record: Mapping[str, Any]) -> None:
    validated = validate_artifact_retention_scheduler_lease_record(record)
    dialect_name = _dialect_name(session)
    session.execute(
        text(_scheduler_lease_upsert_sql(dialect_name)),
        _scheduler_lease_params(validated),
    )


def _scheduler_lease_upsert_sql(dialect_name: str) -> str:
    guardrails_expr = _json_sql_expression(dialect_name, "guardrails")
    metadata_expr = _json_sql_expression(dialect_name, "metadata")
    return f"""
        INSERT INTO ae_artifact_retention_scheduler_leases (
            scheduler_id,
            lease_record_id,
            lease_record_schema_version,
            service_id,
            lease_owner_id,
            lease_token,
            lease_status,
            fencing_token,
            acquired_at,
            expires_at,
            released_at,
            last_observed_at,
            operation,
            tick_id,
            idempotency_key,
            guardrails,
            metadata,
            updated_at
        )
        VALUES (
            :scheduler_id,
            :lease_record_id,
            :lease_record_schema_version,
            :service_id,
            :lease_owner_id,
            :lease_token,
            :lease_status,
            :fencing_token,
            :acquired_at,
            :expires_at,
            :released_at,
            :last_observed_at,
            :operation,
            :tick_id,
            :idempotency_key,
            {guardrails_expr},
            {metadata_expr},
            :updated_at
        )
        ON CONFLICT (scheduler_id) DO UPDATE SET
            lease_record_id = excluded.lease_record_id,
            lease_record_schema_version = excluded.lease_record_schema_version,
            service_id = excluded.service_id,
            lease_owner_id = excluded.lease_owner_id,
            lease_token = excluded.lease_token,
            lease_status = excluded.lease_status,
            fencing_token = excluded.fencing_token,
            acquired_at = excluded.acquired_at,
            expires_at = excluded.expires_at,
            released_at = excluded.released_at,
            last_observed_at = excluded.last_observed_at,
            operation = excluded.operation,
            tick_id = excluded.tick_id,
            idempotency_key = excluded.idempotency_key,
            guardrails = excluded.guardrails,
            metadata = excluded.metadata,
            updated_at = excluded.updated_at
    """


def _scheduler_lease_params(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scheduler_id": record["scheduler_id"],
        "lease_record_id": record["lease_record_id"],
        "lease_record_schema_version": record["lease_record_schema_version"],
        "service_id": record["service_id"],
        "lease_owner_id": record["lease_owner_id"],
        "lease_token": record["lease_token"],
        "lease_status": record["lease_status"],
        "fencing_token": record["fencing_token"],
        "acquired_at": record["acquired_at"],
        "expires_at": record["expires_at"],
        "released_at": record["released_at"],
        "last_observed_at": record["last_observed_at"],
        "operation": record["operation"],
        "tick_id": record["tick_id"],
        "idempotency_key": record["idempotency_key"],
        "guardrails": json.dumps(record["guardrails"]),
        "metadata": json.dumps(record["metadata"]),
        "updated_at": record["last_observed_at"],
    }


def _scheduler_lease_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    record = {
        "lease_record_schema_version": data["lease_record_schema_version"],
        "lease_record_id": data["lease_record_id"],
        "service_id": data["service_id"],
        "scheduler_id": data["scheduler_id"],
        "lease_owner_id": data["lease_owner_id"],
        "lease_token": data["lease_token"],
        "lease_status": data["lease_status"],
        "fencing_token": data["fencing_token"],
        "acquired_at": _datetime_value(data["acquired_at"]),
        "expires_at": _datetime_value(data["expires_at"]),
        "released_at": _datetime_value(data["released_at"]),
        "last_observed_at": _datetime_value(data["last_observed_at"]),
        "operation": data["operation"],
        "tick_id": data["tick_id"],
        "idempotency_key": data["idempotency_key"],
        "guardrails": _json_value(data["guardrails"], {}),
        "metadata": _json_value(data["metadata"], {}),
    }
    return validate_artifact_retention_scheduler_lease_record(record)


def _lease_matches_request(
    record: Mapping[str, Any],
    request: Mapping[str, Any],
) -> bool:
    validated_record = validate_artifact_retention_scheduler_lease_record(record)
    return (
        validated_record["lease_status"] == "HELD"
        and validated_record["scheduler_id"] == request["scheduler_id"]
        and validated_record["lease_owner_id"] == request["lease_owner_id"]
        and validated_record["operation"] == request["operation"]
        and validated_record["idempotency_key"] == request["idempotency_key"]
    )


def _lease_blocks_acquisition(
    record: Mapping[str, Any],
    *,
    requested_at: str,
) -> bool:
    validated_record = validate_artifact_retention_scheduler_lease_record(record)
    if validated_record["lease_status"] != "HELD":
        return False
    expires_at = parse_artifact_retention_timestamp(
        validated_record["expires_at"],
        field_name="expires_at",
    )
    requested_dt = parse_artifact_retention_timestamp(
        requested_at,
        field_name="requested_at",
    )
    return expires_at > requested_dt


def _next_fencing_token(record: Mapping[str, Any] | None) -> int:
    if record is None:
        return 1
    return validate_artifact_retention_scheduler_lease_record(record)["fencing_token"] + 1


def _json_sql_expression(dialect_name: str, field_name: str) -> str:
    if dialect_name == "postgresql":
        return f"CAST(:{field_name} AS JSONB)"
    return f":{field_name}"


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return fallback
        return decoded if decoded is not None else fallback
    return fallback


def _datetime_value(value: Any) -> str | None:
    if value is None:
        return None
    return format_artifact_retention_timestamp(
        parse_artifact_retention_timestamp(str(value), field_name="timestamp")
    )


def _dialect_name(session: Session) -> str:
    bind = session.get_bind()
    return bind.dialect.name if bind is not None else ""


def _lease_store_unavailable() -> ArtifactHandoffError:
    return ArtifactHandoffError(
        status_code=503,
        error_code="ae.artifact_retention_scheduler_lease_store_unavailable",
        detail="AE artifact retention scheduler lease store is unavailable.",
        retryable=True,
    )


def normalize_artifact_retention_scheduler_lease_operation(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None or normalized not in ARTIFACT_RETENTION_SCHEDULER_LEASE_OPERATIONS:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_operation_invalid",
            detail="Artifact retention scheduler lease operation is invalid.",
        )
    return normalized


def normalize_artifact_retention_scheduler_lease_record_status(value: Any) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_status_invalid",
            detail="Artifact retention scheduler lease status is required.",
        )
    normalized = normalized.upper()
    if normalized not in ARTIFACT_RETENTION_SCHEDULER_LEASE_RECORD_STATUSES:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_record_status_invalid",
            detail="Artifact retention scheduler lease status is invalid.",
        )
    return normalized


def normalize_artifact_retention_scheduler_lease_ttl_seconds(
    value: int | str | None,
) -> int:
    if value is None:
        return ARTIFACT_RETENTION_SCHEDULER_TICK_LOCK_TTL_SECONDS
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_ttl_invalid",
            detail="Artifact retention scheduler lease TTL must be an integer.",
        ) from exc
    if (
        normalized < MIN_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS
        or normalized > MAX_ARTIFACT_RETENTION_SCHEDULER_LEASE_TTL_SECONDS
    ):
        raise ArtifactHandoffError(
            status_code=422,
            error_code="ae.artifact_retention_scheduler_lease_ttl_invalid",
            detail="Artifact retention scheduler lease TTL is outside the supported range.",
        )
    return normalized


def artifact_retention_scheduler_lease_idempotency_key(
    *,
    scheduler_id: str,
    lease_owner_id: str,
    operation: str,
    requested_at: str,
) -> str:
    basis = {
        "scheduler_id": scheduler_id,
        "lease_owner_id": lease_owner_id,
        "operation": operation,
        "requested_at": requested_at,
    }
    return f"ae-artifact-retention-scheduler-lease:{sha256_json(basis)}"


def _scheduler_lease_guardrails() -> dict[str, bool]:
    return {
        "lease_required_before_tick": True,
        "manual_once_runner": True,
        "daemon_auto_start_allowed": False,
        "scheduler_daemon_started": False,
        "continuous_loop_started": False,
        "continuous_loop_allowed_before_lease": False,
        "physical_delete_automation_enabled": False,
    }


def _scheduler_lease_metadata() -> dict[str, bool]:
    return {
        "metadata_only": True,
        "database_url_included": False,
        "storage_path_included": False,
        "raw_artifact_payload_included": False,
        "raw_execution_payload_included": False,
        "job_enqueued": False,
        "worker_executed": False,
    }


def _request_time_from_config(config: Mapping[str, Any]) -> str:
    return str(config.get("checked_at") or "2026-09-01T00:00:00Z")


def _lease_token(request: Mapping[str, Any], *, fencing_token: int) -> str:
    basis = {
        "scheduler_id": request["scheduler_id"],
        "lease_owner_id": request["lease_owner_id"],
        "operation": request["operation"],
        "requested_at": request["requested_at"],
        "fencing_token": fencing_token,
        "idempotency_key": request["idempotency_key"],
    }
    return str(uuid5(NAMESPACE_URL, f"ae-artifact-retention-lease:{sha256_json(basis)}"))


def _lease_record_id(*, scheduler_id: str, lease_token: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"ae-artifact-retention-lease-record:{scheduler_id}:{lease_token}",
        )
    )


def _required_text(value: Any, field_name: str, error_code: str) -> str:
    normalized = optional_text(value)
    if normalized is None:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} is required for artifact retention scheduler lease.",
        )
    return normalized


def _positive_int(value: Any, field_name: str, error_code: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a positive integer.",
        ) from exc
    if normalized < 1:
        raise ArtifactHandoffError(
            status_code=422,
            error_code=error_code,
            detail=f"{field_name} must be a positive integer.",
        )
    return normalized
