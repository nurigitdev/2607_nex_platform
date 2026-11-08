from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

NSL_WRITE_EVIDENCE_SCHEMA_VERSION = "ae_nsl_write_evidence.v1"

_IDEMPOTENCY_KEY = re.compile(r"^idem:sha256:[0-9a-f]{64}$")
_RECORD_FIELDS = (
    "tenant_id",
    "nsl_execution_id",
    "business_operation_id",
    "invocation_id",
    "write_node_id",
    "tool_id",
    "contract_hash",
    "approval_request_id",
    "idempotency_key",
    "payload_hash",
    "write_intent_hash",
    "precondition_evidence_id",
    "requested_at",
    "record_hash",
)


@dataclass
class NslWriteEvidenceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyNslWriteEvidencePort:
    """Durable AE adapter for NSL WRITE_REQUESTED evidence."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        public_api: NslV02PublicApiAdapter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(public_api, NslV02PublicApiAdapter):
            raise _invalid("NSL write evidence requires the admitted public API.")
        for name in (
            "write_evidence_port",
            "write_attempt_record",
            "write_requested_receipt",
        ):
            if not isinstance(getattr(public_api, name, None), type):
                raise _invalid(f"Admitted NSL {name} is unavailable.")
        self._session_factory = session_factory
        self._public_api = public_api
        self._clock = clock or (lambda: datetime.now(UTC))

    async def record_requested(self, record: Any) -> Any:
        if not isinstance(record, self._public_api.write_attempt_record):
            raise _invalid("NSL write attempt record type is invalid.")
        return await asyncio.to_thread(self._record_sync, record)

    def get(
        self,
        *,
        tenant_id: str,
        nsl_execution_id: str,
        invocation_id: str,
    ) -> dict[str, Any] | None:
        identity = {
            "tenant_id": _text("tenant_id", tenant_id, 128),
            "nsl_execution_id": _text("nsl_execution_id", nsl_execution_id, 256),
            "invocation_id": _text("invocation_id", invocation_id, 256),
        }
        try:
            with self._session_factory() as session:
                return self._load(session, identity)
        except NslWriteEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _record_sync(self, record: Any) -> Any:
        proposed = _record_data(record)
        persisted_at = _utc("persisted_at", self._clock())
        if persisted_at < proposed["requested_at"]:
            raise _invalid("persisted_at cannot predate requested_at.")
        proposed["persisted_at"] = persisted_at
        identity = {
            "tenant_id": proposed["tenant_id"],
            "nsl_execution_id": proposed["nsl_execution_id"],
            "invocation_id": proposed["invocation_id"],
        }
        try:
            with self._session_factory() as session:
                session.execute(text(_INSERT_SQL), proposed)
                saved = self._load(session, identity)
                if saved is None:
                    raise _unavailable()
                if any(saved[field] != proposed[field] for field in _RECORD_FIELDS):
                    raise NslWriteEvidenceError(
                        "ae.nsl_write_evidence_conflict",
                        "WRITE_REQUESTED identity is already bound to different evidence.",
                    )
                session.commit()
        except NslWriteEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return self._receipt(saved)

    def _load(
        self, session: Session, identity: Mapping[str, str]
    ) -> dict[str, Any] | None:
        row = session.execute(text(_SELECT_SQL), dict(identity)).mappings().first()
        if row is None:
            return None
        try:
            saved = _saved_data(row)
        except NslWriteEvidenceError as exc:
            raise _integrity_failed() from exc
        try:
            reconstructed = self._public_api.write_attempt_record(
                tenant_id=saved["tenant_id"],
                execution_id=saved["nsl_execution_id"],
                business_operation_id=saved["business_operation_id"],
                invocation_id=saved["invocation_id"],
                node_id=saved["write_node_id"],
                tool_id=saved["tool_id"],
                contract_hash=saved["contract_hash"],
                approval_request_id=saved["approval_request_id"],
                idempotency_key=saved["idempotency_key"],
                payload_hash=saved["payload_hash"],
                write_intent_hash=saved["write_intent_hash"],
                precondition_evidence_id=saved["precondition_evidence_id"],
                requested_at=saved["requested_at"],
            )
            valid = (
                isinstance(reconstructed, self._public_api.write_attempt_record)
                and _hash("record_hash", reconstructed.record_hash)
                == saved["record_hash"]
            )
        except Exception as exc:
            raise _integrity_failed() from exc
        if not valid:
            raise _integrity_failed()
        return {"schema_version": NSL_WRITE_EVIDENCE_SCHEMA_VERSION, **saved}

    def _receipt(self, saved: Mapping[str, Any]) -> Any:
        durable_ref = f"ae-postgresql:ae_nsl_write_evidence:{saved['record_hash']}"
        try:
            receipt = self._public_api.write_requested_receipt(
                record_hash=saved["record_hash"],
                durable_ref=durable_ref,
                persisted_at=saved["persisted_at"],
                durable=True,
            )
            compatible = (
                isinstance(receipt, self._public_api.write_requested_receipt)
                and receipt.record_hash == saved["record_hash"]
                and receipt.durable_ref == durable_ref
                and receipt.persisted_at == saved["persisted_at"]
                and receipt.durable is True
            )
        except Exception as exc:
            raise _invalid(
                "Admitted NSL WriteRequestedReceipt is incompatible."
            ) from exc
        if not compatible:
            raise _invalid("NSL WriteRequestedReceipt changed durable bindings.")
        return receipt


def _record_data(record: Any) -> dict[str, Any]:
    requested_at = _utc("requested_at", record.requested_at)
    try:
        record_hash = record.record_hash
    except Exception as exc:
        raise _invalid("NSL WriteAttemptRecord record_hash is unavailable.") from exc
    return {
        "tenant_id": _text("tenant_id", record.tenant_id, 128),
        "nsl_execution_id": _text("execution_id", record.execution_id, 256),
        "business_operation_id": _text(
            "business_operation_id", record.business_operation_id, 256
        ),
        "invocation_id": _text("invocation_id", record.invocation_id, 256),
        "write_node_id": _text("node_id", record.node_id, 256),
        "tool_id": _text("tool_id", record.tool_id, 256),
        "contract_hash": _hash("contract_hash", record.contract_hash),
        "approval_request_id": _text(
            "approval_request_id", record.approval_request_id, 256
        ),
        "idempotency_key": _key(record.idempotency_key),
        "payload_hash": _hash("payload_hash", record.payload_hash),
        "write_intent_hash": _hash("write_intent_hash", record.write_intent_hash),
        "precondition_evidence_id": _text(
            "precondition_evidence_id", record.precondition_evidence_id, 256
        ),
        "requested_at": requested_at,
        "record_hash": _hash("record_hash", record_hash),
    }


def _saved_data(row: Mapping[str, Any]) -> dict[str, Any]:
    saved = dict(row)
    for field, maximum in (
        ("tenant_id", 128),
        ("nsl_execution_id", 256),
        ("business_operation_id", 256),
        ("invocation_id", 256),
        ("write_node_id", 256),
        ("tool_id", 256),
        ("approval_request_id", 256),
        ("precondition_evidence_id", 256),
    ):
        saved[field] = _text(field, saved[field], maximum)
    for field in (
        "contract_hash",
        "payload_hash",
        "write_intent_hash",
        "record_hash",
    ):
        saved[field] = _hash(field, saved[field])
    saved["idempotency_key"] = _key(saved["idempotency_key"])
    saved["requested_at"] = _utc(
        "requested_at", saved["requested_at"], require_utc=False
    )
    saved["persisted_at"] = _utc(
        "persisted_at", saved["persisted_at"], require_utc=False
    )
    if saved["persisted_at"] < saved["requested_at"]:
        raise _integrity_failed()
    return saved


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(f"{field} must be a bounded non-empty string.")
    return normalized


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} must be a SHA-256 hash reference.") from exc


def _key(value: object) -> str:
    key = _text("idempotency_key", value, 76)
    if _IDEMPOTENCY_KEY.fullmatch(key) is None:
        raise _invalid("idempotency_key must be an idem SHA-256 value.")
    return key


def _utc(field: str, value: object, *, require_utc: bool = True) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _invalid(f"{field} must be a UTC timestamp.") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise _invalid(f"{field} must be a UTC timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{field} must use UTC.")
    if require_utc and parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _invalid(f"{field} must use UTC.")
    return parsed.astimezone(UTC)


def _invalid(detail: str) -> NslWriteEvidenceError:
    return NslWriteEvidenceError("ae.nsl_write_evidence_invalid", detail)


def _integrity_failed() -> NslWriteEvidenceError:
    return NslWriteEvidenceError(
        "ae.nsl_write_evidence_integrity_failed",
        "WRITE_REQUESTED evidence failed integrity verification.",
    )


def _unavailable() -> NslWriteEvidenceError:
    return NslWriteEvidenceError(
        "ae.nsl_write_evidence_store_unavailable",
        "AE WRITE_REQUESTED evidence store is unavailable.",
        True,
    )


_INSERT_SQL = """
    INSERT INTO ae_nsl_write_evidence (
        tenant_id, nsl_execution_id, business_operation_id, invocation_id,
        write_node_id, tool_id, contract_hash, approval_request_id,
        idempotency_key, payload_hash, write_intent_hash,
        precondition_evidence_id, requested_at, record_hash, persisted_at
    ) VALUES (
        :tenant_id, :nsl_execution_id, :business_operation_id, :invocation_id,
        :write_node_id, :tool_id, :contract_hash, :approval_request_id,
        :idempotency_key, :payload_hash, :write_intent_hash,
        :precondition_evidence_id, :requested_at, :record_hash, :persisted_at
    ) ON CONFLICT DO NOTHING
"""

_SELECT_SQL = """
    SELECT tenant_id, nsl_execution_id, business_operation_id, invocation_id,
           write_node_id, tool_id, contract_hash, approval_request_id,
           idempotency_key, payload_hash, write_intent_hash,
           precondition_evidence_id, requested_at, record_hash, persisted_at
      FROM ae_nsl_write_evidence
     WHERE tenant_id = :tenant_id
       AND nsl_execution_id = :nsl_execution_id
       AND invocation_id = :invocation_id
"""
