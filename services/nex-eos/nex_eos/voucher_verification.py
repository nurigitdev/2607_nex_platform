from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .attachments import EOS_VOUCHER_ATTACHMENT_TABLE
from .business_transactions import EOS_BUSINESS_OPERATION_TABLE
from .vouchers import EOS_VOUCHER_DRAFT_LINE_TABLE, EOS_VOUCHER_DRAFT_TABLE

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EosVoucherVerificationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


class SqlAlchemyEosVoucherVerificationQuery:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def verify(
        self,
        *,
        tenant_id: str,
        voucher_id: str,
        business_operation_id: str,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        voucher_id = _uuid("voucher_id", voucher_id)
        business_operation_id = _uuid("business_operation_id", business_operation_id)
        try:
            with self._session_factory() as session:
                operation = (
                    session.execute(
                        select(EOS_BUSINESS_OPERATION_TABLE).where(
                            EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == tenant_id,
                            EOS_BUSINESS_OPERATION_TABLE.c.business_operation_id
                            == business_operation_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                voucher = (
                    session.execute(
                        select(EOS_VOUCHER_DRAFT_TABLE).where(
                            EOS_VOUCHER_DRAFT_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_DRAFT_TABLE.c.voucher_id == voucher_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                lines = (
                    session.execute(
                        select(EOS_VOUCHER_DRAFT_LINE_TABLE)
                        .where(
                            EOS_VOUCHER_DRAFT_LINE_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_DRAFT_LINE_TABLE.c.voucher_id == voucher_id,
                        )
                        .order_by(EOS_VOUCHER_DRAFT_LINE_TABLE.c.line_no)
                    )
                    .mappings()
                    .all()
                )
                attachments = (
                    session.execute(
                        select(EOS_VOUCHER_ATTACHMENT_TABLE)
                        .where(
                            EOS_VOUCHER_ATTACHMENT_TABLE.c.tenant_id == tenant_id,
                            EOS_VOUCHER_ATTACHMENT_TABLE.c.voucher_id == voucher_id,
                        )
                        .order_by(EOS_VOUCHER_ATTACHMENT_TABLE.c.attachment_id)
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise EosVoucherVerificationError(
                "EOS_VOUCHER_VERIFICATION_UNAVAILABLE",
                "EOS Voucher verification read is unavailable.",
                status_code=503,
                retryable=True,
            ) from exc
        if operation is None or voucher is None:
            raise EosVoucherVerificationError(
                "EOS_VOUCHER_VERIFICATION_NOT_FOUND",
                "Voucher verification target was not found in tenant scope.",
                status_code=404,
            )
        result = operation.get("result_json")
        if (
            operation.get("commit_state") != "COMMITTED"
            or not isinstance(result, Mapping)
            or result.get("voucher_id") != voucher_id
        ):
            raise EosVoucherVerificationError(
                "EOS_VOUCHER_VERIFICATION_BINDING_INVALID",
                "Voucher and BusinessOperation are not a confirmed committed binding.",
                status_code=409,
            )
        if not lines:
            raise _state_invalid("Voucher has no persisted lines.")
        balance = sum(
            (Decimal(str(line["signed_amount"])) for line in lines),
            Decimal("0.00"),
        )
        if balance != Decimal("0.00"):
            raise _state_invalid("Voucher line balance is invalid.")
        state = _stable_state(voucher, lines, attachments)
        return {
            "schema_version": "eos_voucher_verification.v1",
            "tenant_id": tenant_id,
            "voucher_ref": {"type": "eos.voucher_draft", "id": voucher_id},
            "business_operation_id": business_operation_id,
            "operation": str(operation["operation"]),
            "idempotency_key": str(operation["idempotency_key"]),
            "business_transaction_ref": {
                "type": "eos.business_operation",
                "id": business_operation_id,
            },
            "payload_hash": str(operation["payload_hash"]),
            "commit_state": "COMMITTED",
            "voucher_state": str(voucher["state"]),
            "voucher_version": int(voucher["version"]),
            "project_ref": {
                "type": "eos.project",
                "id": str(voucher["project_id"]),
            },
            "line_count": len(lines),
            "attachment_count": len(attachments),
            "balance": format(balance, ".2f"),
            "stable_business_state_hash": semantic_sha256_hash_ref(state),
            "last_observed_at": _wire_time(operation.get("committed_at")),
        }


def _stable_state(
    voucher: Mapping[str, Any],
    lines: list[Mapping[str, Any]],
    attachments: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "voucher_id": str(voucher["voucher_id"]),
        "project_id": str(voucher["project_id"]),
        "voucher_type": str(voucher["voucher_type"]),
        "currency": str(voucher["currency"]),
        "transaction_date": _date_text(voucher["transaction_date"]),
        "description": str(voucher["description"]),
        "requester_ref": {
            "type": str(voucher["requester_ref_type"]),
            "id": str(voucher["requester_id"]),
        },
        "source_ref": {
            "type": str(voucher["source_ref_type"]),
            "id": str(voucher["source_id"]),
        },
        "state": str(voucher["state"]),
        "version": int(voucher["version"]),
        "lines": [
            {
                "line_no": int(line["line_no"]),
                "account_id": str(line["account_id"]),
                "signed_amount": format(Decimal(str(line["signed_amount"])), ".2f"),
                "economic_category": str(line["economic_category"]),
                "description": line["description"],
                "evidence_refs": list(line["evidence_refs"]),
            }
            for line in lines
        ],
        "attachments": [
            {
                "attachment_id": str(item["attachment_id"]),
                "object_ref": str(item["object_ref"]),
                "object_version_ref": item["object_version_ref"],
                "media_type": str(item["media_type"]),
                "size_bytes": int(item["size_bytes"]),
                "content_sha256": str(item["content_sha256"]),
            }
            for item in attachments
        ],
    }


def _date_text(value: object) -> str:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _state_invalid("Voucher transaction date is invalid.")
    return value.isoformat()


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise _state_invalid("BusinessOperation committed time is invalid.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise EosVoucherVerificationError(
            "EOS_VOUCHER_VERIFICATION_INVALID",
            f"{field_name} has an invalid format.",
            status_code=422,
        )
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise EosVoucherVerificationError(
            "EOS_VOUCHER_VERIFICATION_INVALID",
            f"{field_name} must be a UUID.",
            status_code=422,
        ) from exc


def _state_invalid(detail: str) -> EosVoucherVerificationError:
    return EosVoucherVerificationError(
        "EOS_VOUCHER_VERIFICATION_STATE_INVALID",
        detail,
        status_code=503,
    )
