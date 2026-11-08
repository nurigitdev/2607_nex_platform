from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_BUSINESS_OPERATION_TABLE

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class EosBusinessQueryError(RuntimeError):
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


class SqlAlchemyEosBusinessOperationQuery:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get(self, *, tenant_id: str, business_operation_id: str) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        business_operation_id = _uuid("business_operation_id", business_operation_id)
        try:
            with self._session_factory() as session:
                row = (
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
        except SQLAlchemyError as exc:
            raise EosBusinessQueryError(
                "EOS_BUSINESS_QUERY_UNAVAILABLE",
                "EOS BusinessOperation query is unavailable.",
                status_code=503,
                retryable=True,
            ) from exc
        if row is None:
            raise EosBusinessQueryError(
                "EOS_BUSINESS_OPERATION_NOT_FOUND",
                "BusinessOperation was not found in tenant scope.",
                status_code=404,
            )
        return _projection(row)


def _projection(row: Mapping[str, Any]) -> dict[str, Any]:
    stored_state = row.get("commit_state")
    result = row.get("result_json")
    if stored_state == "COMMITTED":
        if not isinstance(result, Mapping) or not isinstance(
            result.get("voucher_id"), str
        ):
            raise _corrupt()
        commit_state = "COMMITTED"
        reconciliation_status = "COMMITTED_CONFIRMED"
        voucher_ref = {"type": "eos.voucher_draft", "id": result["voucher_id"]}
        attachment_batch_id, attachment_manifest_hash, attachment_ids = (
            _attachment_lineage(result)
        )
        observed_at = row.get("committed_at")
    elif stored_state == "NOT_COMMITTED":
        commit_state = "NOT_COMMITTED"
        reconciliation_status = "NOT_COMMITTED_CONFIRMED"
        voucher_ref = None
        attachment_batch_id, attachment_manifest_hash, attachment_ids = None, None, []
        observed_at = row.get("committed_at") or row.get("created_at")
    elif stored_state == "PENDING":
        commit_state = "UNKNOWN_COMMIT_STATE"
        reconciliation_status = "RECONCILIATION_REQUIRED"
        voucher_ref = None
        attachment_batch_id, attachment_manifest_hash, attachment_ids = None, None, []
        observed_at = row.get("created_at")
    else:
        raise _corrupt()
    return {
        "schema_version": "eos_business_operation_query.v1",
        "tenant_id": str(row["tenant_id"]),
        "business_operation_id": str(row["business_operation_id"]),
        "operation": str(row["operation"]),
        "payload_hash": str(row["payload_hash"]),
        "commit_state": commit_state,
        "business_transaction_ref": {
            "type": "eos.business_operation",
            "id": str(row["business_operation_id"]),
        },
        "voucher_ref": voucher_ref,
        "attachment_batch_id": attachment_batch_id,
        "attachment_manifest_hash": attachment_manifest_hash,
        "attachment_ids": attachment_ids,
        "reconciliation_status": reconciliation_status,
        "last_observed_at": _wire_time(observed_at),
    }


def _attachment_lineage(
    result: Mapping[str, Any],
) -> tuple[str | None, str | None, list[str]]:
    batch_id = result.get("attachment_batch_id")
    manifest_hash = result.get("attachment_manifest_hash")
    raw_ids = result.get("attachment_ids", [])
    if batch_id is None and manifest_hash is None and raw_ids == []:
        return None, None, []
    if (
        not isinstance(batch_id, str)
        or not isinstance(manifest_hash, str)
        or not isinstance(raw_ids, list)
        or not raw_ids
        or any(not isinstance(item, str) for item in raw_ids)
    ):
        raise _corrupt()
    try:
        batch_id = str(uuid.UUID(batch_id))
        validate_hash_ref(manifest_hash)
        attachment_ids = sorted(str(uuid.UUID(item)) for item in raw_ids)
    except (ValueError, TypeError, AttributeError) as exc:
        raise _corrupt() from exc
    if attachment_ids != raw_ids or len(set(attachment_ids)) != len(attachment_ids):
        raise _corrupt()
    return batch_id, manifest_hash, attachment_ids


def _wire_time(value: object) -> str:
    if not isinstance(value, datetime):
        raise _corrupt()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _scoped_id(field_name: str, value: object) -> str:
    if not isinstance(value, str) or _SCOPED_ID.fullmatch(value) is None:
        raise EosBusinessQueryError(
            "EOS_BUSINESS_QUERY_INVALID",
            f"{field_name} has an invalid format.",
            status_code=422,
        )
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise EosBusinessQueryError(
            "EOS_BUSINESS_QUERY_INVALID",
            f"{field_name} must be a UUID.",
            status_code=422,
        ) from exc


def _corrupt() -> EosBusinessQueryError:
    return EosBusinessQueryError(
        "EOS_BUSINESS_OPERATION_STATE_INVALID",
        "BusinessOperation state is incomplete or inconsistent.",
        status_code=503,
    )
