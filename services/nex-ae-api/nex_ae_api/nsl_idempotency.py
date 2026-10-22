from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter

NSL_IDEMPOTENCY_EVIDENCE_SCHEMA_VERSION = "ae_nsl_idempotency_evidence.v1"

_IDEMPOTENCY_KEY = re.compile(r"^idem:sha256:[0-9a-f]{64}$")
_EVIDENCE_FIELDS = (
    "tenant_id",
    "business_operation_id",
    "write_node_id",
    "tool_id",
    "contract_hash",
    "idempotency_key",
    "payload_hash",
    "provider_guarantee_ref",
    "retained_until",
)
_IDENTITY_FIELDS = (
    "tenant_id",
    "business_operation_id",
    "write_node_id",
    "tool_id",
    "contract_hash",
    "idempotency_key",
)


@dataclass
class NslIdempotencyEvidenceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class SqlAlchemyNslIdempotencyEvidencePort:
    """Durable AE adapter for the admitted NSL IdempotencyEvidencePort."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        public_api: NslV02PublicApiAdapter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(public_api, NslV02PublicApiAdapter):
            raise _invalid("NSL idempotency requires the admitted public API.")
        for name in (
            "idempotency_evidence_port",
            "idempotency_evidence_record",
            "idempotency_reservation",
            "idempotency_disposition",
        ):
            if not isinstance(getattr(public_api, name, None), type):
                raise _invalid(f"Admitted NSL {name} is unavailable.")
        self._session_factory = session_factory
        self._public_api = public_api
        self._clock = clock or (lambda: datetime.now(UTC))

    async def reserve(self, evidence: Any) -> Any:
        if not isinstance(evidence, self._public_api.idempotency_evidence_record):
            raise _invalid("NSL idempotency evidence type is invalid.")
        return await asyncio.to_thread(self._reserve_sync, evidence)

    def get(self, *, tenant_id: str, idempotency_key: str) -> dict[str, Any] | None:
        tenant = _text("tenant_id", tenant_id, 128)
        key = _key(idempotency_key)
        try:
            with self._session_factory() as session:
                return _load_by_key(session, tenant_id=tenant, idempotency_key=key)
        except NslIdempotencyEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def _reserve_sync(self, evidence: Any) -> Any:
        proposed = _evidence_data(evidence)
        proposed["evidence_hash"] = _integrity(proposed)
        proposed["created_at"] = _utc("created_at", self._clock())
        try:
            with self._session_factory() as session:
                result = session.execute(text(_INSERT_SQL), proposed)
                created = result.rowcount == 1
                saved = _load_by_key(
                    session,
                    tenant_id=proposed["tenant_id"],
                    idempotency_key=proposed["idempotency_key"],
                )
                if saved is None:
                    saved = _load_by_business_identity(session, proposed)
                if saved is None:
                    raise _unavailable()
                disposition = _disposition(saved, proposed, created=created)
                session.commit()
        except NslIdempotencyEvidenceError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return self._reservation(disposition, evidence)

    def _reservation(self, disposition: str, evidence: Any) -> Any:
        try:
            disposition_value = getattr(
                self._public_api.idempotency_disposition, disposition
            )
            reservation = self._public_api.idempotency_reservation(
                disposition=disposition_value,
                evidence=evidence,
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise _invalid("Admitted NSL IdempotencyReservation is incompatible.") from exc
        try:
            compatible = (
                isinstance(reservation, self._public_api.idempotency_reservation)
                and reservation.disposition is disposition_value
                and reservation.evidence == evidence
                and reservation.business_result_ref is None
            )
        except Exception as exc:
            raise _invalid(
                "NSL IdempotencyReservation compatibility check failed."
            ) from exc
        if not compatible:
            raise _invalid("NSL IdempotencyReservation changed evidence bindings.")
        return reservation


def _evidence_data(evidence: Any) -> dict[str, Any]:
    record = {
        "tenant_id": _text("tenant_id", evidence.tenant_id, 128),
        "business_operation_id": _text(
            "business_operation_id", evidence.business_operation_id, 256
        ),
        "write_node_id": _text("write_node_id", evidence.write_node_id, 256),
        "tool_id": _text("tool_id", evidence.tool_id, 256),
        "contract_hash": _hash("contract_hash", evidence.contract_hash),
        "idempotency_key": _key(evidence.idempotency_key),
        "payload_hash": _hash("payload_hash", evidence.payload_hash),
        "provider_guarantee_ref": _text(
            "provider_guarantee_ref", evidence.provider_guarantee_ref, 512
        ),
        "retained_until": _utc("retained_until", evidence.retained_until),
    }
    return record


def _load_by_key(
    session: Session, *, tenant_id: str, idempotency_key: str
) -> dict[str, Any] | None:
    return _load(
        session,
        "tenant_id = :tenant_id AND idempotency_key = :idempotency_key",
        {"tenant_id": tenant_id, "idempotency_key": idempotency_key},
    )


def _load_by_business_identity(
    session: Session, proposed: Mapping[str, Any]
) -> dict[str, Any] | None:
    return _load(
        session,
        "tenant_id = :tenant_id "
        "AND business_operation_id = :business_operation_id "
        "AND write_node_id = :write_node_id",
        {
            "tenant_id": proposed["tenant_id"],
            "business_operation_id": proposed["business_operation_id"],
            "write_node_id": proposed["write_node_id"],
        },
    )


def _load(
    session: Session, predicate: str, params: Mapping[str, Any]
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                "SELECT tenant_id, business_operation_id, write_node_id, "
                "tool_id, contract_hash, idempotency_key, payload_hash, "
                "provider_guarantee_ref, retained_until, evidence_hash, "
                f"created_at FROM ae_nsl_idem_evidence WHERE {predicate}"
            ),
            dict(params),
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    saved = dict(row)
    for field, maximum in (
        ("tenant_id", 128),
        ("business_operation_id", 256),
        ("write_node_id", 256),
        ("tool_id", 256),
        ("provider_guarantee_ref", 512),
    ):
        saved[field] = _text(field, saved[field], maximum)
    saved["contract_hash"] = _hash("contract_hash", saved["contract_hash"])
    saved["idempotency_key"] = _key(saved["idempotency_key"])
    saved["payload_hash"] = _hash("payload_hash", saved["payload_hash"])
    saved["retained_until"] = _utc(
        "retained_until", saved["retained_until"], require_utc=False
    )
    saved["evidence_hash"] = _hash("evidence_hash", saved["evidence_hash"])
    saved["created_at"] = _utc(
        "created_at", saved["created_at"], require_utc=False
    )
    if saved["evidence_hash"] != _integrity(saved):
        raise NslIdempotencyEvidenceError(
            "ae.nsl_idempotency_integrity_failed",
            "NSL idempotency evidence failed integrity verification.",
        )
    return {
        "schema_version": NSL_IDEMPOTENCY_EVIDENCE_SCHEMA_VERSION,
        **saved,
    }


def _disposition(
    saved: Mapping[str, Any], proposed: Mapping[str, Any], *, created: bool
) -> str:
    if any(saved[field] != proposed[field] for field in _IDENTITY_FIELDS):
        return "CONFLICT"
    if saved["payload_hash"] != proposed["payload_hash"]:
        return "CONFLICT"
    return "CREATED" if created else "REUSED"


def _integrity(record: Mapping[str, Any]) -> str:
    return semantic_sha256_hash_ref(
        {
            field: (
                record[field].isoformat().replace("+00:00", "Z")
                if isinstance(record[field], datetime)
                else record[field]
            )
            for field in _EVIDENCE_FIELDS
        }
    )


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


def _utc(
    field: str, value: object, *, require_utc: bool = True
) -> datetime:
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


def _invalid(detail: str) -> NslIdempotencyEvidenceError:
    return NslIdempotencyEvidenceError("ae.nsl_idempotency_invalid", detail)


def _unavailable() -> NslIdempotencyEvidenceError:
    return NslIdempotencyEvidenceError(
        "ae.nsl_idempotency_store_unavailable",
        "AE NSL idempotency evidence store is unavailable.",
        True,
    )


_INSERT_SQL = """
    INSERT INTO ae_nsl_idem_evidence (
        tenant_id, business_operation_id, write_node_id, tool_id,
        contract_hash, idempotency_key, payload_hash,
        provider_guarantee_ref, retained_until, evidence_hash, created_at
    ) VALUES (
        :tenant_id, :business_operation_id, :write_node_id, :tool_id,
        :contract_hash, :idempotency_key, :payload_hash,
        :provider_guarantee_ref, :retained_until, :evidence_hash, :created_at
    ) ON CONFLICT DO NOTHING
"""
