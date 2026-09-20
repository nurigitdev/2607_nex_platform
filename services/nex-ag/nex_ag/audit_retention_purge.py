from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ag.audit_retention import _sha256_json
from nex_ag.audit_retention_archive import (
    InMemoryAgArchiveReceiptStore,
    _receipt_from_row,
    _receipt_select_sql,
)


AG_RETENTION_PURGE_EXECUTION_SCHEMA_VERSION = "ag_retention_purge_execution.v1"
ALLOWED_PURGE_MODES = frozenset({"DRY_RUN", "EXECUTE"})
ALLOWED_SOURCE_KINDS = frozenset({"operational_event", "evidence_export"})
EXECUTE_CONFIRMATION = "PURGE"


@dataclass(frozen=True)
class AgRetentionPurgeError(RuntimeError):
    error_code: str
    detail: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.detail


class AgRetentionPurgeStore(Protocol):
    def assess(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> Mapping[str, Any]: ...

    def purge(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> Mapping[str, Any]: ...


class InMemoryAgRetentionPurgeStore:
    def __init__(
        self,
        *,
        receipt_store: InMemoryAgArchiveReceiptStore,
        source_records: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    ) -> None:
        self.receipt_store = receipt_store
        self.source_records = {
            key: dict(value) for key, value in (source_records or {}).items()
        }

    def assess(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        return _build_assessment(
            source_kind=source_kind,
            source_id=source_id,
            source_record=self.source_records.get((source_kind, source_id)),
            receipt=self.receipt_store.get_by_source(
                source_kind=source_kind,
                source_id=source_id,
            ),
            as_of=as_of,
        )

    def purge(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        assessment = self.assess(
            source_kind=source_kind,
            source_id=source_id,
            as_of=as_of,
        )
        if assessment["idempotent_noop"]:
            return {**assessment, "deleted_count": 0}
        if not assessment["eligible"]:
            return {**assessment, "deleted_count": 0}
        del self.source_records[(source_kind, source_id)]
        receipt = self.receipt_store.records[assessment["archive_id"]]
        receipt["archive_status"] = "PURGED"
        receipt["purged_at"] = assessment["as_of"]
        receipt["updated_at"] = assessment["as_of"]
        return {
            **assessment,
            "eligible": False,
            "reason": "purged",
            "archive_status": "PURGED",
            "idempotent_noop": False,
            "deleted_count": 1,
        }


class SqlAlchemyAgRetentionPurgeStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def assess(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                source_record, receipt = _load_source_and_receipt(
                    session,
                    source_kind=source_kind,
                    source_id=source_id,
                    lock=False,
                )
            return _build_assessment(
                source_kind=source_kind,
                source_id=source_id,
                source_record=source_record,
                receipt=receipt,
                as_of=as_of,
            )
        except SQLAlchemyError as exc:
            raise _purge_store_unavailable() from exc

    def purge(
        self,
        *,
        source_kind: str,
        source_id: str,
        as_of: str,
    ) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                source_record, receipt = _load_source_and_receipt(
                    session,
                    source_kind=source_kind,
                    source_id=source_id,
                    lock=True,
                )
                assessment = _build_assessment(
                    source_kind=source_kind,
                    source_id=source_id,
                    source_record=source_record,
                    receipt=receipt,
                    as_of=as_of,
                )
                if assessment["idempotent_noop"] or not assessment["eligible"]:
                    return {**assessment, "deleted_count": 0}
                delete_result = session.execute(
                    text(_source_delete_sql(source_kind)),
                    {"source_id": source_id},
                )
                update_result = session.execute(
                    text(
                        """
                        UPDATE ag_ret_archives
                        SET archive_status = 'PURGED',
                            purged_at = :as_of,
                            updated_at = :as_of
                        WHERE archive_id = :archive_id
                          AND archive_status = 'SEALED'
                        """
                    ),
                    {
                        "archive_id": assessment["archive_id"],
                        "as_of": assessment["as_of"],
                    },
                )
                if int(delete_result.rowcount or 0) != 1 or int(
                    update_result.rowcount or 0
                ) != 1:
                    raise AgRetentionPurgeError(
                        error_code="ag.retention.purge_concurrent_change",
                        detail="AG retention source changed during purge.",
                        status_code=409,
                    )
                session.commit()
                return {
                    **assessment,
                    "eligible": False,
                    "reason": "purged",
                    "archive_status": "PURGED",
                    "idempotent_noop": False,
                    "deleted_count": 1,
                }
        except AgRetentionPurgeError:
            raise
        except SQLAlchemyError as exc:
            raise _purge_store_unavailable() from exc


def execute_ag_retention_purge(
    *,
    store: AgRetentionPurgeStore,
    policy: Mapping[str, Any],
    source_kind: str,
    source_id: str,
    as_of: str,
    mode: str = "DRY_RUN",
    confirmation: str | None = None,
) -> dict[str, Any]:
    normalized_kind = _source_kind(source_kind)
    normalized_id = _required_text(source_id, "source_id")
    normalized_as_of = _timestamp(_parse_timestamp(as_of, field="as_of"))
    normalized_mode = _purge_mode(mode)
    purge_policy = policy.get("purge")
    if not isinstance(purge_policy, Mapping):
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_policy_invalid",
            detail="AG retention purge policy is invalid.",
        )
    assessment = dict(
        store.assess(
            source_kind=normalized_kind,
            source_id=normalized_id,
            as_of=normalized_as_of,
        )
    )
    if normalized_mode == "DRY_RUN":
        return _execution_response(
            assessment=assessment,
            mode=normalized_mode,
            status=_assessment_status(assessment),
            deleted_count=0,
        )
    if purge_policy.get("execute_enabled") is not True:
        return _execution_response(
            assessment={**assessment, "reason": "execute_disabled"},
            mode=normalized_mode,
            status="BLOCKED",
            deleted_count=0,
        )
    if confirmation != EXECUTE_CONFIRMATION:
        return _execution_response(
            assessment={**assessment, "reason": "confirmation_required"},
            mode=normalized_mode,
            status="BLOCKED",
            deleted_count=0,
        )
    outcome = dict(
        store.purge(
            source_kind=normalized_kind,
            source_id=normalized_id,
            as_of=normalized_as_of,
        )
    )
    return _execution_response(
        assessment=outcome,
        mode=normalized_mode,
        status=(
            "PURGED"
            if outcome.get("deleted_count") == 1
            else _assessment_status(outcome)
        ),
        deleted_count=int(outcome.get("deleted_count") or 0),
    )


def _build_assessment(
    *,
    source_kind: str,
    source_id: str,
    source_record: Mapping[str, Any] | None,
    receipt: Mapping[str, Any] | None,
    as_of: str,
) -> dict[str, Any]:
    normalized_as_of = _timestamp(_parse_timestamp(as_of, field="as_of"))
    base = {
        "source_kind": source_kind,
        "source_id": source_id,
        "as_of": normalized_as_of,
        "archive_id": receipt.get("archive_id") if receipt else None,
        "archive_status": receipt.get("archive_status") if receipt else None,
        "eligible": False,
        "idempotent_noop": False,
        "reason": "receipt_missing",
    }
    if receipt is None:
        return base
    if receipt.get("archive_status") == "PURGED":
        return {
            **base,
            "idempotent_noop": source_record is None,
            "reason": (
                "already_purged" if source_record is None else "purged_source_present"
            ),
        }
    if receipt.get("archive_status") != "SEALED":
        return {**base, "reason": "receipt_not_sealed"}
    if receipt.get("archive_provider_mode") != "external":
        return {**base, "reason": "external_receipt_required"}
    purge_after = receipt.get("purge_after")
    if purge_after is None:
        return {**base, "reason": "purge_after_missing"}
    if _parse_timestamp(purge_after, field="purge_after") > _parse_timestamp(
        normalized_as_of,
        field="as_of",
    ):
        return {**base, "reason": "archive_grace_active"}
    if source_record is None:
        return {**base, "reason": "source_missing"}
    if _sha256_json(source_record) != receipt.get("source_content_sha256"):
        return {**base, "reason": "source_hash_mismatch"}
    return {**base, "eligible": True, "reason": "eligible"}


def _execution_response(
    *,
    assessment: Mapping[str, Any],
    mode: str,
    status: str,
    deleted_count: int,
) -> dict[str, Any]:
    return {
        "purge_execution_schema_version": (
            AG_RETENTION_PURGE_EXECUTION_SCHEMA_VERSION
        ),
        "mode": mode,
        "status": status,
        "source_kind": assessment.get("source_kind"),
        "source_id": assessment.get("source_id"),
        "archive_id": assessment.get("archive_id"),
        "archive_status": assessment.get("archive_status"),
        "reason": assessment.get("reason"),
        "checked_at": assessment.get("as_of"),
        "deleted_count": deleted_count,
        "idempotent_noop": assessment.get("idempotent_noop") is True,
        "raw_payload_included": False,
        "confirmation_included": False,
    }


def _assessment_status(assessment: Mapping[str, Any]) -> str:
    if assessment.get("idempotent_noop") is True:
        return "NOOP"
    return "ELIGIBLE" if assessment.get("eligible") is True else "BLOCKED"


def _load_source_and_receipt(
    session: Session,
    *,
    source_kind: str,
    source_id: str,
    lock: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    dialect = str(session.bind.dialect.name) if session.bind else ""
    lock_clause = " FOR UPDATE" if lock and dialect == "postgresql" else ""
    source_row = session.execute(
        text(_source_select_sql(source_kind) + lock_clause),
        {"source_id": source_id},
    ).mappings().first()
    receipt_row = session.execute(
        text(
            _receipt_select_sql(
                "source_kind = :source_kind AND source_id = :source_id"
            )
            + lock_clause
        ),
        {"source_kind": source_kind, "source_id": source_id},
    ).mappings().first()
    return (
        dict(source_row) if source_row is not None else None,
        _receipt_from_row(receipt_row) if receipt_row is not None else None,
    )


def _source_select_sql(source_kind: str) -> str:
    if source_kind == "operational_event":
        return """
            SELECT event_id, service_id, event_type, severity, trace_id,
                   request_id, subject_type, subject_id, message, details,
                   created_at
            FROM service_operational_events
            WHERE event_id = :source_id
        """
    if source_kind == "evidence_export":
        return """
            SELECT export_id, export_schema_version, target_service,
                   target_kind, target_id, trace_id, request_id,
                   operator_type, operator_id, tenant_id, operator_ref,
                   export_status, export_format, redaction_profile,
                   evidence_manifest, evidence_hash, evidence_item_count,
                   metadata, created_at, updated_at
            FROM ag_ev_exports
            WHERE export_id = :source_id
        """
    raise AgRetentionPurgeError(
        error_code="ag.retention.purge_source_kind_invalid",
        detail="AG retention source kind is invalid.",
    )


def _source_delete_sql(source_kind: str) -> str:
    if source_kind == "operational_event":
        return "DELETE FROM service_operational_events WHERE event_id = :source_id"
    if source_kind == "evidence_export":
        return "DELETE FROM ag_ev_exports WHERE export_id = :source_id"
    raise AgRetentionPurgeError(
        error_code="ag.retention.purge_source_kind_invalid",
        detail="AG retention source kind is invalid.",
    )


def _source_kind(value: str) -> str:
    normalized = _required_text(value, "source_kind").lower()
    if normalized not in ALLOWED_SOURCE_KINDS:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_source_kind_invalid",
            detail="AG retention source kind is invalid.",
        )
    return normalized


def _purge_mode(value: str) -> str:
    normalized = _required_text(value, "mode").upper()
    if normalized not in ALLOWED_PURGE_MODES:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_mode_invalid",
            detail="AG retention purge mode is invalid.",
        )
    return normalized


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_field_required",
            detail=f"{field} is required.",
        )
    return value.strip()


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AgRetentionPurgeError(
                error_code="ag.retention.purge_timestamp_invalid",
                detail=f"{field} must be an ISO-8601 timestamp.",
            ) from exc
    else:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_timestamp_invalid",
            detail=f"{field} must be an ISO-8601 timestamp.",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_timestamp_timezone_required",
            detail=f"{field} must include a timezone.",
        )
    return parsed.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _purge_store_unavailable() -> AgRetentionPurgeError:
    return AgRetentionPurgeError(
        error_code="ag.retention.purge_store_unavailable",
        detail="AG retention purge store is unavailable.",
        status_code=503,
    )
