from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_approval_requests import (
    ProtectedApprovalRequestError,
    canonical_approval_request_data,
)

PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION = "ae_platform_approval_evidence.v1"

_INTEGRITY_FIELDS = (
    "tenant_id",
    "agent_execution_id",
    "executable_step_id",
    "nsl_execution_id",
    "business_operation_id",
    "approval_id",
    "approval_request_id",
    "skill_semantic_hash",
    "decision",
    "approver_id",
    "decided_at",
    "expires_at",
    "payload_hash",
    "write_intent_hash",
    "approval_work_item_ref",
    "oa_decision_ref",
    "protected_request_ref",
)
_PUBLIC_FIELDS = (
    "schema_version",
    *_INTEGRITY_FIELDS,
    "evidence_integrity",
    "created_at",
)
_TERMINAL_STATE = {"APPROVE": "APPROVED", "REJECT": "REJECTED"}
_PROTECTED_REQUEST_REF = re.compile(
    r"^ae://nsl-approval-requests/[0-9a-f]{2}/[0-9a-f]{64}\.json$"
)


@dataclass(frozen=True)
class PlatformApprovalEvidenceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


def build_platform_approval_evidence(
    *,
    approval_request: object,
    protected_request: Mapping[str, Any],
    wait_registration: Mapping[str, Any],
    approval_work_item: Mapping[str, Any],
    approval_decision: Mapping[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    request = _approval_request(approval_request)
    protected = _mapping("protected_request", protected_request)
    wait = _mapping("wait_registration", wait_registration)
    work_item = _mapping("approval_work_item", approval_work_item)
    decision = _mapping("approval_decision", approval_decision)

    tenant_id = _required("tenant_id", request["tenant_id"], 128)
    request_id = _required("approval_request_id", request["approval_request_id"], 256)
    nsl_execution_id = _required("execution_id", request["execution_id"], 256)
    business_operation_id = _required(
        "business_operation_id", request["business_operation_id"], 256
    )
    agent_execution_id = _uuid("agent_execution_id", wait.get("agent_execution_id"))
    executable_step_id = _required(
        "executable_step_id", wait.get("executable_step_id"), 256
    )
    checkpoint_version = wait.get("checkpoint_version")
    if (
        wait.get("wait_type") != "NSL_APPROVAL"
        or not isinstance(checkpoint_version, int)
        or isinstance(checkpoint_version, bool)
        or checkpoint_version < 1
        or wait.get("state") == "CANCELLED"
    ):
        raise _invalid("Approval evidence requires an active NSL approval wait.")

    request_lineage = {
        "tenant_id": tenant_id,
        "approval_request_id": request_id,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
    }
    _require_fields(protected, request_lineage, "protected request")
    _require_fields(wait, request_lineage, "wait registration")
    if wait.get("external_ref") != request_id:
        raise _invalid("Wait registration request identity is invalid.")

    protected_ref = _protected_ref(protected.get("protected_request_ref"))
    protected_hash = _hash_ref(
        "approval_request_hash", protected.get("approval_request_hash")
    )
    work_lineage = {
        **request_lineage,
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "protected_request_ref": protected_ref,
    }
    _require_fields(work_item, work_lineage, "approval work item")
    if (
        work_item.get("approval_domain") != "NSL_WRITE"
        or work_item.get("approval_provider_type") != "NSL"
        or work_item.get("source_ref") != request_id
        or work_item.get("approval_target_ref") != request_id
        or work_item.get("semantic_hash") != protected_hash
    ):
        raise _invalid("Approval work item does not bind the protected NSL request.")

    work_item_ref = _uuid(
        "approval_work_item_ref", work_item.get("approval_work_item_id")
    )
    decision_value = _decision(decision.get("decision"))
    if work_item.get("state") != _TERMINAL_STATE[decision_value]:
        raise _invalid("Approval work item is not in the matching terminal state.")
    if (
        decision.get("tenant_id") != tenant_id
        or decision.get("approval_work_item_id") != work_item_ref
        or decision.get("authorized_by_oa") is not True
    ):
        raise _invalid("Approval decision authority lineage is invalid.")
    _uuid("decision_id", decision.get("decision_id"))
    decision_version = decision.get("decision_version")
    if (
        not isinstance(decision_version, int)
        or isinstance(decision_version, bool)
        or decision_version < 1
    ):
        raise _invalid("Approval decision version is invalid.")
    _hash_ref(
        "authorization_revision_hash",
        decision.get("authorization_revision_hash"),
    )

    decided_at = _timestamp("decided_at", decision.get("decided_at"))
    authorization_checked_at = _timestamp(
        "authorization_checked_at", decision.get("authorization_checked_at")
    )
    if _as_datetime(authorization_checked_at) > _as_datetime(decided_at):
        raise _invalid("OA authorization evidence follows the approval decision.")
    expires_at = _optional_timestamp("expires_at", request.get("expires_at"))
    work_item_expires_at = _optional_timestamp(
        "work_item.expires_at", work_item.get("expires_at")
    )
    if expires_at != work_item_expires_at:
        raise _invalid("Approval expiration differs across request and work item.")
    if expires_at is not None and _as_datetime(decided_at) >= _as_datetime(expires_at):
        raise _invalid("Approval decision was made after request expiration.")

    record = {
        "schema_version": PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "approval_id": _required("approval_id", request["approval_id"], 256),
        "approval_request_id": request_id,
        "skill_semantic_hash": _hash_ref(
            "skill_semantic_hash", request["skill_semantic_hash"]
        ),
        "decision": decision_value,
        "approver_id": _required("approver_id", decision.get("decided_by"), 128),
        "decided_at": decided_at,
        "expires_at": expires_at,
        "payload_hash": _hash_ref("payload_hash", request["payload_hash"]),
        "write_intent_hash": _required(
            "write_intent_hash", request["write_intent_hash"], 256
        ),
        "approval_work_item_ref": work_item_ref,
        "oa_decision_ref": _required(
            "oa_decision_ref", decision.get("oa_decision_ref"), 128
        ),
        "protected_request_ref": protected_ref,
        "created_at": _timestamp("created_at", created_at),
    }
    record["evidence_integrity"] = _integrity(record)
    return validate_platform_approval_evidence(record)


def validate_platform_approval_evidence(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(_PUBLIC_FIELDS):
        raise _invalid("Platform ApprovalEvidence fields are invalid.")
    record = dict(value)
    if record["schema_version"] != PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION:
        raise _invalid("Platform ApprovalEvidence schema_version is invalid.")
    record["tenant_id"] = _required("tenant_id", record["tenant_id"], 128)
    record["agent_execution_id"] = _uuid(
        "agent_execution_id", record["agent_execution_id"]
    )
    record["executable_step_id"] = _required(
        "executable_step_id", record["executable_step_id"], 256
    )
    for field in (
        "nsl_execution_id",
        "business_operation_id",
        "approval_id",
        "approval_request_id",
        "write_intent_hash",
    ):
        record[field] = _required(field, record[field], 256)
    record["skill_semantic_hash"] = _hash_ref(
        "skill_semantic_hash", record["skill_semantic_hash"]
    )
    record["payload_hash"] = _hash_ref("payload_hash", record["payload_hash"])
    record["decision"] = _decision(record["decision"])
    record["approver_id"] = _required("approver_id", record["approver_id"], 128)
    record["decided_at"] = _timestamp("decided_at", record["decided_at"])
    record["expires_at"] = _optional_timestamp("expires_at", record["expires_at"])
    if record["expires_at"] is not None and _as_datetime(
        record["decided_at"]
    ) >= _as_datetime(record["expires_at"]):
        raise _invalid("Approval evidence decision must precede expiration.")
    record["approval_work_item_ref"] = _uuid(
        "approval_work_item_ref", record["approval_work_item_ref"]
    )
    record["oa_decision_ref"] = _required(
        "oa_decision_ref", record["oa_decision_ref"], 128
    )
    record["protected_request_ref"] = _protected_ref(record["protected_request_ref"])
    record["evidence_integrity"] = _hash_ref(
        "evidence_integrity", record["evidence_integrity"]
    )
    record["created_at"] = _timestamp("created_at", record["created_at"])
    if record["evidence_integrity"] != _integrity(record):
        raise PlatformApprovalEvidenceError(
            "ae.approval_evidence_integrity_failed",
            "Platform ApprovalEvidence failed integrity verification.",
        )
    return record


class SqlAlchemyPlatformApprovalEvidenceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_or_get(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        record = validate_platform_approval_evidence(evidence)
        try:
            with self._session_factory() as session:
                session.execute(text(_INSERT_SQL), record)
                saved = _load(
                    session,
                    tenant_id=record["tenant_id"],
                    approval_request_id=record["approval_request_id"],
                )
                if saved is None:
                    raise _unavailable()
                if not _same_immutable_record(saved, record):
                    raise _conflict()
                session.commit()
                return saved
        except PlatformApprovalEvidenceError:
            raise
        except IntegrityError as exc:
            raise _conflict() from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get(self, *, tenant_id: str, approval_request_id: str) -> dict[str, Any] | None:
        tenant_id = _required("tenant_id", tenant_id, 128)
        approval_request_id = _required("approval_request_id", approval_request_id, 256)
        try:
            with self._session_factory() as session:
                return _load(
                    session,
                    tenant_id=tenant_id,
                    approval_request_id=approval_request_id,
                )
        except PlatformApprovalEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_by_work_item_ref(
        self, *, tenant_id: str, approval_work_item_ref: str
    ) -> dict[str, Any] | None:
        tenant_id = _required("tenant_id", tenant_id, 128)
        approval_work_item_ref = _uuid("approval_work_item_ref", approval_work_item_ref)
        try:
            with self._session_factory() as session:
                row = (
                    session.execute(
                        text(
                            "SELECT approval_request_id FROM ae_approval_evidence "
                            "WHERE tenant_id = :tenant_id "
                            "AND approval_work_item_ref = :approval_work_item_ref"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "approval_work_item_ref": approval_work_item_ref,
                        },
                    )
                    .mappings()
                    .first()
                )
                return (
                    None
                    if row is None
                    else _load(
                        session,
                        tenant_id=tenant_id,
                        approval_request_id=str(row["approval_request_id"]),
                    )
                )
        except PlatformApprovalEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc


def _load(
    session: Session, *, tenant_id: str, approval_request_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, agent_execution_id, executable_step_id, "
                "nsl_execution_id, business_operation_id, approval_id, "
                "approval_request_id, skill_semantic_hash, decision, "
                "approver_id, decided_at, expires_at, payload_hash, "
                "write_intent_hash, approval_work_item_ref, oa_decision_ref, "
                "protected_request_ref, evidence_integrity, created_at "
                "FROM ae_approval_evidence WHERE tenant_id = :tenant_id "
                "AND approval_request_id = :approval_request_id"
            ),
            {
                "tenant_id": tenant_id,
                "approval_request_id": approval_request_id,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return validate_platform_approval_evidence(
        {
            "schema_version": PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION,
            **dict(row),
        }
    )


def _approval_request(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        value = _ApprovalRequestSnapshot(dict(value))
    try:
        return canonical_approval_request_data(value)
    except ProtectedApprovalRequestError as exc:
        raise _invalid(exc.detail) from exc


@dataclass(frozen=True)
class _ApprovalRequestSnapshot:
    value: dict[str, Any]

    def to_data(self) -> dict[str, Any]:
        return dict(self.value)


def _mapping(field: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object.")
    return dict(value)


def _require_fields(
    actual: Mapping[str, Any], expected: Mapping[str, Any], boundary: str
) -> None:
    if any(str(actual.get(field)) != str(value) for field, value in expected.items()):
        raise _invalid(f"Platform ApprovalEvidence {boundary} lineage differs.")


def _integrity(record: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {field: record.get(field) for field in _INTEGRITY_FIELDS}
    )


def _same_immutable_record(
    saved: Mapping[str, Any], proposed: Mapping[str, Any]
) -> bool:
    return all(
        saved.get(field) == proposed.get(field)
        for field in _PUBLIC_FIELDS
        if field != "created_at"
    )


def _required(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return value.strip()


def _uuid(field: str, value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a UUID.") from exc


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc


def _decision(value: object) -> str:
    if value not in _TERMINAL_STATE:
        raise _invalid("Approval decision must be APPROVE or REJECT.")
    return str(value)


def _protected_ref(value: object) -> str:
    normalized = _required("protected_request_ref", value, 512)
    if _PROTECTED_REQUEST_REF.fullmatch(normalized) is None:
        raise _invalid("protected_request_ref is outside the AE private boundary.")
    return normalized


def _timestamp(field: str, value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid(f"{field} must be an RFC3339 timestamp.") from exc
    else:
        raise _invalid(f"{field} must be an RFC3339 timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must include a timezone.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_timestamp(field: str, value: object) -> str | None:
    return None if value is None else _timestamp(field, value)


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _invalid(detail: str) -> PlatformApprovalEvidenceError:
    return PlatformApprovalEvidenceError("ae.approval_evidence_invalid", detail)


def _conflict() -> PlatformApprovalEvidenceError:
    return PlatformApprovalEvidenceError(
        "ae.approval_evidence_idempotency_conflict",
        "Approval evidence identity is already bound to different semantics.",
    )


def _unavailable() -> PlatformApprovalEvidenceError:
    return PlatformApprovalEvidenceError(
        "ae.approval_evidence_store_unavailable",
        "AE Platform ApprovalEvidence store is unavailable.",
        True,
    )


_INSERT_SQL = """
    INSERT INTO ae_approval_evidence (
        tenant_id, agent_execution_id, executable_step_id,
        nsl_execution_id, business_operation_id, approval_id,
        approval_request_id, skill_semantic_hash, decision, approver_id,
        decided_at, expires_at, payload_hash, write_intent_hash,
        approval_work_item_ref, oa_decision_ref, protected_request_ref,
        evidence_integrity, created_at
    ) VALUES (
        :tenant_id, :agent_execution_id, :executable_step_id,
        :nsl_execution_id, :business_operation_id, :approval_id,
        :approval_request_id, :skill_semantic_hash, :decision, :approver_id,
        :decided_at, :expires_at, :payload_hash, :write_intent_hash,
        :approval_work_item_ref, :oa_decision_ref, :protected_request_ref,
        :evidence_integrity, :created_at
    ) ON CONFLICT (tenant_id, approval_request_id) DO NOTHING
"""
